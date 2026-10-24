"""Approved reconstruction through ExperimentService; no execution/storage engine."""

from collections.abc import Collection, Mapping
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import math
from numbers import Real

from .experiment import ExperimentService
from .schemas import (
    ExperimentRequest, ExperimentResult, MetricComparison, MetricTolerance,
    ReplicationReport, ReplicationSpecification,
)


_MISSING = object()


def specification_digest(specification: ReplicationSpecification) -> str:
    """Digest binds approval to all proposal data, excluding approval itself."""
    specification = ReplicationSpecification.model_validate(specification.model_dump())
    data = json.dumps(specification.model_dump(mode='json', exclude={'approval'}),
                      sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def _number(value):
    if value is None or value is _MISSING:
        return None, 'missing'
    if isinstance(value, bool) or not isinstance(value, Real):
        return None, 'non-numeric'
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None, 'non-finite'
    return (value, None) if math.isfinite(value) else (None, 'non-finite')


def compare_metric(name: str, published, reproduced=_MISSING, *,
                   absolute_tolerance: float, relative_tolerance: float) -> MetricComparison:
    """Compare finite scalar numbers without rounding or an implicit epsilon.

    |actual-reference| <= atol + rtol*|reference|. Decimal arithmetic on the exact
    float representations avoids overflow turning a different result into inf<=inf.
    Non-numeric/non-finite values are unavailable, never coerced from strings.
    """
    tolerance = MetricTolerance(absolute_tolerance=absolute_tolerance,
                                relative_tolerance=relative_tolerance)
    reference, reference_error = _number(published)
    actual, actual_error = _number(reproduced)
    base = dict(name=name, published_value=reference, reproduced_value=actual,
                **tolerance.model_dump())
    if reference_error or actual_error:
        reason = (f'Published metric is {reference_error}' if reference_error
                  else f'Reproduced metric is {actual_error}')
        return MetricComparison(**base, status='unavailable', reason=reason)
    warnings = []

    def finite_output(value, label):
        result = float(value)
        if not math.isfinite(result):
            warnings.append(f'{label} exceeds finite JSON float range; reported as null')
            return None
        if result == 0 and value != 0:
            warnings.append(f'{label} is below JSON float resolution; reported as null')
            return None
        return result

    with localcontext() as context:
        # Sufficient for exact subtraction/multiplication of finite binary64 operands.
        context.prec = 2200
        ref, value = Decimal.from_float(reference), Decimal.from_float(actual)
        difference = abs(value - ref)
        bound = (Decimal.from_float(tolerance.absolute_tolerance)
                 + Decimal.from_float(tolerance.relative_tolerance) * abs(ref))
        agrees = difference <= bound
        absolute = finite_output(difference, 'Absolute difference')
        relative = percentage = None
        if reference != 0:
            ratio = difference / abs(ref)
            relative = finite_output(ratio, 'Relative difference')
            percentage = finite_output(ratio * 100, 'Percentage difference')
        else:
            warnings.append('Relative and percentage differences are undefined for a zero reference')
    return MetricComparison(**base, status='match' if agrees else 'different', agrees=agrees,
                            absolute_difference=absolute, relative_difference=relative,
                            percentage_difference=percentage, warnings=warnings)


def compare_metrics(published_metrics, reproduced: Mapping) -> list[MetricComparison]:
    return [compare_metric(metric.name, metric.value, reproduced.get(metric.name, _MISSING),
                           absolute_tolerance=metric.absolute_tolerance,
                           relative_tolerance=metric.relative_tolerance)
            for metric in published_metrics]


def _missing_inputs(spec, available_datasets, available_assets):
    missing = []
    if spec.code is None:
        missing.append('Reconstruction implementation code')
    if spec.parameters is None:
        missing.append('Explicit reconstruction parameters (use {} for none)')
    if spec.random_seed is None:
        missing.append('Explicit reconstruction random seed')
    if spec.dataset_required is None:
        missing.append('Whether an external dataset is required')
    if spec.dataset_required and spec.dataset is None:
        missing.append('Required dataset reference')
    if spec.dataset is not None and spec.dataset.dataset_id not in available_datasets:
        missing.append('Backend-confirmed availability of the specified dataset')
    if any(asset not in available_assets for asset in spec.required_asset_ids):
        missing.append('Backend-confirmed availability of required assets/code/weights')
    return missing


def _methodology(spec, missing_inputs):
    limitations = spec.limitations
    missing = list(limitations.missing_methodological_details)
    for label, value in (
        ('Experiment title', spec.experiment_title), ('Algorithm or method', spec.algorithm),
        ('Published dependency requirements', spec.required_dependencies),
        ('Published experimental parameters', spec.published_parameters),
        ('Published random seed', spec.published_random_seed),
        ('Evaluation metric definitions', spec.evaluation_metrics),
    ):
        if value is None:
            missing.append(label)
    if not spec.evaluation_metrics:
        missing.append('Nonempty evaluation metric list')
    if not spec.published_metrics:
        missing.append('Published numerical reference results')
    for metric in spec.published_metrics:
        if metric.value is None:
            missing.append(f'Published numerical value for metric: {metric.name}')
    reference_names = {metric.name for metric in spec.published_metrics}
    if spec.evaluation_metrics and set(spec.evaluation_metrics) != reference_names:
        missing.append('Evaluation metrics and published reference metrics do not fully correspond')
    if spec.dataset is not None:
        if spec.dataset.description is None:
            missing.append('Dataset description')
        if spec.dataset.original_sha256 is None and spec.dataset.processed is None:
            missing.append('Dataset content hash')
    if limitations.original_conditions_known is not True:
        missing.append('Original experimental conditions are not confirmed known')
    if limitations.conditions_match_publication is not True:
        missing.append('Reconstruction conditions are not confirmed to match the source')
    missing = list(dict.fromkeys(missing + missing_inputs))
    approximate = bool(
        limitations.assumptions or limitations.substituted_parameters
        or limitations.unavailable_datasets or limitations.unavailable_code_or_weights
        or limitations.conditions_match_publication is False
        or (spec.published_parameters is not None and spec.parameters is not None
            and spec.published_parameters != spec.parameters)
        or (spec.published_random_seed is not None and spec.random_seed is not None
            and spec.published_random_seed != spec.random_seed)
    )
    if missing_inputs:
        completeness = 'insufficient_information'
    elif approximate:
        completeness = 'approximate_reconstruction'
    elif missing or spec.paper.source_kind == 'unverified':
        completeness = 'partially_specified'
    else:
        completeness = 'fully_specified'
    return completeness, missing


class ReplicationService:
    def __init__(self, experiment_service: ExperimentService):
        self.experiments = experiment_service

    def run(self, specification: ReplicationSpecification | dict, *,
            available_dataset_ids: Collection[str] = (),
            available_asset_ids: Collection[str] = ()) -> ReplicationReport:
        spec = ReplicationSpecification.model_validate(
            specification.model_dump() if isinstance(specification, ReplicationSpecification) else specification)
        digest = specification_digest(spec)
        missing_inputs = _missing_inputs(spec, available_dataset_ids, available_asset_ids)
        completeness, missing_information = _methodology(spec, missing_inputs)
        warnings = ['Numerical agreement alone does not establish faithful scientific reproduction.',
                    'Methodology assessment uses supplied declarations; it is not an independent audit of code or conditions.']
        if spec.paper.source_kind != 'publication':
            warnings.append('Reference source is a local demonstration baseline or unverified source, not a verified publication.')
        if spec.limitations.unavailable_datasets:
            warnings.append('Original datasets were reported unavailable; any executed reconstruction is approximate.')
        if spec.limitations.unavailable_code_or_weights:
            warnings.append('Original code or weights were reported unavailable.')
        if spec.limitations.substituted_parameters:
            warnings.append('Experimental components or parameters were explicitly substituted.')
        if spec.published_parameters is not None and spec.parameters is not None and spec.published_parameters != spec.parameters:
            warnings.append('Execution parameters differ from the supplied published parameters.')
        if spec.published_random_seed is not None and spec.random_seed is not None and spec.published_random_seed != spec.random_seed:
            warnings.append('Execution random seed differs from the supplied published seed.')
        execution = None
        approved = (spec.approval.approved and spec.approval.approved_by is not None
                    and spec.approval.specification_sha256 == digest)
        if not approved:
            status = 'approval_required'
            warnings.append('Researcher approval must be recorded for the current specification digest.')
        elif missing_inputs:
            status = 'missing_inputs'
        else:
            dataset_metadata = spec.dataset.model_dump(mode='json') if spec.dataset else None
            request = ExperimentRequest(
                experiment_id=spec.experiment_id, code=spec.code, parameters=spec.parameters,
                random_seed=spec.random_seed, timeout_seconds=spec.timeout_seconds,
                dataset_id=spec.dataset.dataset_id if spec.dataset else None,
                metadata={'replication_specification_sha256': digest,
                          'replication_dataset': dataset_metadata,
                          'processed_dataset': spec.dataset.processed.model_dump(mode='json')
                          if spec.dataset and spec.dataset.processed else None},
            )
            execution = self.experiments.run(request)
            execution = ExperimentResult.model_validate(execution.model_dump())
            if execution.experiment_id != spec.experiment_id:
                raise ValueError('Experiment service returned an unrelated experiment result')
            status = 'completed' if execution.status == 'success' else 'execution_failed'
        actual = dict(execution.metrics) if execution else {}
        comparisons = compare_metrics(spec.published_metrics, actual if status == 'completed' else {})
        if execution is None or status == 'execution_failed':
            numerical = 'not_executed' if execution is None else 'execution_failed'
            for comparison in comparisons:
                comparison.status = numerical
                comparison.reproduced_value = actual.get(comparison.name)
                comparison.reason = 'Experiment was not executed' if execution is None else 'Execution failed; partial metrics are not reproduction evidence'
        else:
            comparable = [item for item in comparisons if item.agrees is not None]
            if not comparable:
                numerical = 'no_comparable_metrics'
            elif any(item.agrees is False for item in comparable):
                numerical = 'some_metrics_differ'
            else:
                numerical = 'all_comparable_agree'
        comparable_count = sum(item.agrees is not None for item in comparisons)
        if comparable_count < len(comparisons) and status == 'completed':
            warnings.append('Some published metrics are unavailable for comparison; agreement covers comparable metrics only.')
        all_agree = None
        if status == 'completed' and comparisons:
            if any(item.agrees is False for item in comparisons):
                all_agree = False
            elif comparable_count == len(comparisons):
                all_agree = True
        reference_names = {item.name for item in spec.published_metrics}
        additional = {name: value for name, value in actual.items() if name not in reference_names}
        dependencies = execution.execution_metadata.get('dependencies', {}) if execution else {}
        if not isinstance(dependencies, dict):
            dependencies = {}
        if execution and execution.execution_metadata.get('artifact_errors'):
            warnings.append('Some figures were not exported; inspect execution_metadata.artifact_errors.')
        summary = (f'Execution: {execution.status if execution else "not_executed"}. '
                   f'Numerical assessment: {numerical}; {comparable_count}/{len(comparisons)} reference metrics comparable. '
                   f'Methodology: {completeness}. Numerical agreement alone does not prove faithful reproduction.')
        return ReplicationReport(
            specification=spec, specification_sha256=digest, paper=spec.paper,
            experiment_id=spec.experiment_id, status=status,
            execution_status=execution.status if execution else 'not_executed', execution=execution,
            published_metrics=spec.published_metrics, reproduced_metrics=actual,
            comparisons=comparisons, additional_metrics=additional, numerical_assessment=numerical,
            all_published_metrics_agree=all_agree, methodology_completeness=completeness,
            missing_information=missing_information, missing_inputs=missing_inputs,
            assumptions=spec.limitations.assumptions, dataset_provenance=spec.dataset,
            code_sha256=execution.execution_metadata.get('code_sha256') if execution else None,
            parameters=spec.parameters, random_seed=spec.random_seed,
            dependency_versions=dependencies, artifacts=execution.artifacts if execution else [],
            execution_duration=execution.execution_time if execution else None,
            warnings=warnings, summary=summary, report_timestamp=datetime.now(timezone.utc).isoformat(),
        )
