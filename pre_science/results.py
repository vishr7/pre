"""Pure, opt-in scientific presentation contracts. No I/O or execution."""
import hashlib
import json
import re
from typing import Literal

from pydantic import Field, JsonValue

from .latex_tables import LatexTableResponse
from .robustness import RobustnessReport
from .statistics import StatisticalReport
from .schemas import (Model, FiniteNumber, ExperimentResult, ReplicationReport, OptimizationResult,
                      DatasetSummary, DatasetProcessingResult, ScientificWorkflowReport, FigureArtifact)


class SourceVersion(Model):
    kind: Literal['code_sha256', 'dataset_sha256', 'request_sha256', 'record_sha256']
    value: str = Field(pattern=r'^[0-9a-f]{64}$')


class ResultMetric(Model):
    name: str
    value: FiniteNumber | None
    role: str = 'measurement'
    observation_count: int | None = None


class DatasetReference(Model):
    dataset_id: str
    source_sha256: str | None = None
    processed_sha256: str | None = None
    artifact_reference: str | None = None


class ResultArtifact(Model):
    artifact_reference: str = Field(pattern=r'^[0-9a-f]{32}-[0-9a-f]{32}$')
    artifact_type: str
    mime_type: str
    sha256: str
    size_bytes: int


class ObservationSeries(Model):
    metric: str
    seeds: list[int]
    values: list[FiniteNumber]
    execution_ids: list[str]
    complete: bool


class ResultEvidence(Model):
    execution_status: str | None = None
    completeness: Literal['complete', 'incomplete', 'unknown'] = 'unknown'
    missing_inputs: list[str] = Field(default_factory=list)
    configuration_available: bool = False
    reviewed_reference_metrics: list[str] = Field(default_factory=list)
    observations: list[ObservationSeries] = Field(default_factory=list)
    preprocessing_issues: list[str] = Field(default_factory=list)
    best_configuration_available: bool = False


class NextAction(Model):
    action_id: str
    title: str
    description: str
    action_type: Literal['review', 'view', 'generate', 'compare', 'draft']
    eligible: bool
    reason: str
    required_inputs: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    source_result_ids: list[str] = Field(default_factory=list)
    suggested_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    execution_authorized: Literal[False] = False


class UnifiedScientificResult(Model):
    result_id: str | None = None
    result_type: Literal['experiment', 'dataset_inspection', 'dataset_processing', 'replication',
                         'optimization', 'robustness', 'statistics', 'latex_table', 'workflow']
    source_id: str | None = None
    source_version: SourceVersion | None = None
    current_source_version: SourceVersion | None = None
    freshness: Literal['unknown', 'matching', 'stale'] = 'unknown'
    status: str
    title: str
    summary: str
    metrics: list[ResultMetric] = Field(default_factory=list)
    parameters: dict[str, JsonValue] | None = None
    dataset_references: list[DatasetReference] = Field(default_factory=list)
    artifacts: list[ResultArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance: dict[str, JsonValue] = Field(default_factory=dict)
    evidence: ResultEvidence = Field(default_factory=ResultEvidence)
    created_at: str | None = None
    original_type: str
    original_payload: dict[str, JsonValue] | None = None
    original_reference: str | None = None
    next_actions: list[NextAction] = Field(default_factory=list)
    all_next_actions: list[NextAction] = Field(default_factory=list)


class ScientificResponse(Model):
    result: str
    scientific: UnifiedScientificResult


SUPPORTED = (ExperimentResult, DatasetSummary, DatasetProcessingResult, ReplicationReport,
             OptimizationResult, RobustnessReport, StatisticalReport, LatexTableResponse, ScientificWorkflowReport)
_PATH = re.compile(r'[A-Za-z]:[\\/][^\s\"\'<>]*|\\\\[\w.-]+\\[^\s\"\'<>]*|(?<![\w:/])/(?:[\w.-]+/)+[\w.-]*|(?<![\w:/])/[\w.-]+\.[A-Za-z0-9]+')
_OPAQUE = re.compile(r'[A-Za-z0-9][A-Za-z0-9:._-]{0,255}')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _public(value):
    if isinstance(value, str):
        if value.startswith('/'):
            return '[local path omitted]'
        return _PATH.sub('[local path omitted]', value)
    if isinstance(value, list):
        return [_public(item) for item in value]
    if isinstance(value, dict):
        return {_public(key): _public(item) for key, item in value.items()}
    return value


def _has_paths(value):
    if isinstance(value, str):
        return value.startswith('/') or bool(_PATH.search(value))
    if isinstance(value, list):
        return any(_has_paths(item) for item in value)
    if isinstance(value, dict):
        return any(_has_paths(key) or _has_paths(item) for key, item in value.items())
    return False


def _dataset(dataset):
    if dataset is None:
        return []
    processed = dataset.processed
    return [DatasetReference(dataset_id=dataset.dataset_id, source_sha256=dataset.original_sha256,
        processed_sha256=processed.sha256 if processed else None,
        artifact_reference=processed.artifact_reference if processed else None)]


def normalize_scientific_result(record, *, result_id=None, original_reference=None,
                                current_source_version: SourceVersion | None = None):
    """Revalidate known records. IDs/timestamps come only from source or caller.

    A caller-supplied opaque original_reference means the backend retains the
    exact original behind authorization. It is required when that record contains
    local paths; public fields redact such paths instead of exposing host URLs.
    """
    if type(record) not in SUPPORTED:
        raise TypeError('Unsupported scientific result type; supply a known validated report model')
    for identifier in (result_id, original_reference):
        if identifier is not None and (not isinstance(identifier, str) or not _OPAQUE.fullmatch(identifier)):
            raise ValueError('Backend record identifiers must be opaque, not paths or URLs')
    record = type(record).model_validate(record.model_dump(warnings=False))
    original = record.model_dump(mode='json')
    json.dumps(original, allow_nan=False)
    paths = _has_paths(original)
    if paths and original_reference is None:
        raise ValueError('Record contains local paths; supply an authorized opaque original_reference')
    values = dict(result_id=result_id, original_type=type(record).__name__, original_reference=original_reference,
                  original_payload=None if original_reference is not None else original)
    evidence = ResultEvidence()
    metrics, artifacts, datasets, warnings, limitations, provenance = [], [], [], [], [], {}
    parameters = version = created = None
    source_id = None
    def metric_map(mapping, role='measurement'):
        metrics.extend(ResultMetric(name=name, value=value, role=role) for name, value in mapping.items())
    def code_version(value):
        return SourceVersion(kind='code_sha256', value=value) if value else None
    def figures(items):
        for artifact in items:
            if isinstance(artifact, FigureArtifact):
                artifacts.append(ResultArtifact(artifact_reference=artifact.artifact_reference, artifact_type='figure',
                    mime_type=artifact.mime_type, sha256=artifact.sha256, size_bytes=artifact.size_bytes))
            else:
                warnings.append('Legacy artifact has no opaque retrieval reference; consult the authorized original record.')
    if isinstance(record, ExperimentResult):
        kind, status, source_id = 'experiment', record.status, record.experiment_id
        title = 'Experiment results'
        metric_map(record.metrics)
        parameters, provenance = record.parameters, record.execution_metadata
        version = code_version(provenance.get('code_sha256'))
        created = provenance.get('submitted_at')
        if provenance.get('dataset_id'):
            datasets = [DatasetReference(dataset_id=provenance['dataset_id'])]
        figures(record.artifacts)
        warnings.extend(provenance.get('artifact_errors', []))
        if record.error:
            warnings.append(f'{record.error.type}: {record.error.message}')
        evidence.execution_status = status
        evidence.completeness = 'complete' if status == 'success' and record.metrics else 'incomplete'
        summary = f'Execution: {status}. Recorded metrics: ' + (', '.join(f'{name}={value!r}' for name, value in record.metrics.items()) or 'none') + f'. Figure artifacts: {len(artifacts)}.'
    elif isinstance(record, (DatasetSummary, DatasetProcessingResult)):
        processed = isinstance(record, DatasetProcessingResult)
        kind, status, source_id = ('dataset_processing' if processed else 'dataset_inspection'), (record.status if processed else 'inspected'), record.dataset_id
        title = 'Dataset processing' if processed else 'Dataset inspection'
        summary_record = record.final_summary or record.original_summary if processed else record
        metric_map({'rows': summary_record.row_count, 'columns': summary_record.column_count, 'duplicate_rows': summary_record.duplicate_rows}, 'dataset_description')
        warnings.extend(summary_record.warnings)
        evidence.preprocessing_issues = [f'{column.name}: {column.missing_count} missing values' for column in summary_record.columns if column.missing_count]
        if summary_record.duplicate_rows:
            evidence.preprocessing_issues.append(f'{summary_record.duplicate_rows} duplicate rows')
        evidence.completeness = 'complete' if status != 'error' else 'incomplete'
        version = SourceVersion(kind='dataset_sha256', value=summary_record.sha256)
        datasets = [DatasetReference(dataset_id=source_id, source_sha256=record.provenance.source_sha256 if processed else record.sha256,
                                     processed_sha256=record.provenance.processed_sha256 if processed else None)]
        if processed:
            provenance = record.provenance.model_dump(mode='json')
            created = record.provenance.processing_timestamp
            warnings.extend(record.original_summary.warnings)
            for entry in record.transformations:
                warnings.extend(entry.warnings)
            if record.error:
                warnings.append(f'{record.error.type}: {record.error.message}')
            if record.artifact:
                artifact = record.artifact
                artifacts.append(ResultArtifact(artifact_reference=artifact.artifact_reference, artifact_type='dataset',
                    mime_type=artifact.mime_type, sha256=artifact.sha256, size_bytes=artifact.size_bytes))
                datasets[0].artifact_reference = artifact.artifact_reference
                values['result_id'] = result_id or artifact.processing_id
        summary = f'Dataset {status}: {summary_record.row_count} rows, {summary_record.column_count} columns; {summary_record.duplicate_rows} duplicate rows.'
    elif isinstance(record, ReplicationReport):
        from .replicate import specification_digest
        kind, status, source_id, title = 'replication', record.status, record.experiment_id, 'Replication comparison'
        metric_map(record.reproduced_metrics)
        parameters, datasets = record.parameters, _dataset(record.dataset_provenance)
        figures(record.artifacts)
        warnings.extend(record.warnings)
        limitations.extend(record.assumptions + record.missing_information)
        for item in record.specification.limitations.model_dump().values():
            if isinstance(item, list):
                limitations.extend(item)
        if record.execution and record.execution.error:
            warnings.append(f'{record.execution.error.type}: {record.execution.error.message}')
        limitations.append('Numerical agreement does not establish scientifically faithful reproduction.')
        evidence.execution_status, evidence.missing_inputs = record.execution_status, record.missing_inputs + record.missing_information
        evidence.configuration_available = bool(record.specification.code and record.parameters is not None)
        approval = record.specification.approval
        if approval.approved and approval.approved_by and approval.specification_sha256 == specification_digest(record.specification):
            evidence.reviewed_reference_metrics = [item.name for item in record.published_metrics]
        evidence.completeness = 'complete' if not evidence.missing_inputs and status == 'completed' else 'incomplete'
        version, created = code_version(record.code_sha256), record.report_timestamp
        provenance = {'specification_sha256': record.specification_sha256, 'paper': record.paper.model_dump(mode='json'), 'dependencies': record.dependency_versions}
        for comparison in record.comparisons:
            warnings.extend(comparison.warnings)
        matched = sum(item.status == 'match' for item in record.comparisons)
        summary = f'Replication {status}: {len(record.comparisons)} reference metrics considered; {matched} recorded tolerance matches. Numerical assessment: {record.numerical_assessment}.'
    elif isinstance(record, OptimizationResult):
        kind, status, source_id, title = 'optimization', record.status, record.study_id, 'Optimization study'
        values['result_id'] = result_id or record.run_id
        if record.best_objective_value is not None:
            metrics.append(ResultMetric(name=record.objective_metric, value=record.best_objective_value, role='best_observed_objective'))
        parameters, datasets = record.best_parameters, _dataset(record.dataset_provenance)
        for trial in record.trials:
            figures(trial.artifacts)
            if trial.error:
                warnings.append(f'Trial {trial.trial_number}: {trial.error.type}: {trial.error.message}')
        warnings.extend(record.warnings)
        if record.error:
            warnings.append(f'{record.error.type}: {record.error.message}')
        limitations.append('Best observed optimization outcomes are selection results, not independent test performance.')
        evidence.configuration_available = bool(record.request.code and record.best_parameters is not None)
        evidence.best_configuration_available = record.best_parameters is not None and record.best_objective_value is not None and record.successful_trial_count > 0
        evidence.missing_inputs = record.missing_inputs
        evidence.completeness = 'complete' if status == 'completed' and record.failed_trial_count == 0 else 'incomplete'
        version, created = code_version(record.code_sha256), record.report_timestamp
        provenance = {'request_sha256': record.request_sha256, 'experiment_id': record.experiment_id,
            'source_replication': record.source_replication.model_dump(mode='json') if record.source_replication else None,
            'sampler': record.sampler_metadata}
        summary = f'Optimization {status}: {len(record.trials)} trials attempted, {record.successful_trial_count} successful, {record.failed_trial_count} failed. Best observed {record.objective_metric}: {record.best_objective_value!r}.'
    elif isinstance(record, RobustnessReport):
        kind, status, source_id, title = 'robustness', record.status, record.study_id, 'Multi-seed robustness'
        parameters, datasets = record.request.parameters, _dataset(record.dataset_provenance)
        figures(record.artifacts)
        warnings.extend(record.warnings)
        for run in record.runs:
            if run.execution:
                figures(run.execution.artifacts)
            if run.error:
                warnings.append(f'Seed {run.seed}: {run.error.type}: {run.error.message}')
            if run.missing_metrics:
                warnings.append(f'Seed {run.seed}: missing metrics: ' + ', '.join(run.missing_metrics))
        for name, item in record.summaries.items():
            metrics.extend([ResultMetric(name=name, value=item.mean, role='mean', observation_count=item.observation_count),
                            ResultMetric(name=name, value=item.sample_std, role='sample_std', observation_count=item.observation_count)])
            observations = [(run.seed, run.execution.metrics[name], run.execution_id) for run in record.runs
                            if run.execution and run.execution.status == 'success' and name in run.execution.metrics]
            evidence.observations.append(ObservationSeries(metric=name, seeds=[item[0] for item in observations],
                values=[item[1] for item in observations], execution_ids=[item[2] for item in observations],
                complete=len(observations) == len(record.requested_seeds) and {item[0] for item in observations} == set(record.requested_seeds)
                    and all(run.execution.random_seed == run.seed for run in record.runs if run.execution)))
        evidence.configuration_available = bool(record.request.code)
        evidence.completeness = 'complete' if status == 'completed' and all(item.complete for item in evidence.observations) else 'incomplete'
        version, created = code_version(record.code_sha256), record.report_timestamp
        provenance = {'specification_sha256': record.specification_sha256, 'experiment_id': record.experiment_id,
                      'source': record.request.source, 'dependencies': record.dependency_versions}
        limitations.append('Repeated seeds and overlapping datasets do not establish independent experimental replications.')
        summary = f'Robustness {status}: {record.completed_runs} successful executions, {record.failed_runs} failed, {len(record.unattempted_seeds)} unattempted. '
        summary += '; '.join(f'{name}: n={item.observation_count}, mean={item.mean!r}, sample SD={item.sample_std!r}' for name, item in record.summaries.items())
    elif isinstance(record, StatisticalReport):
        kind, status, source_id, title = 'statistics', record.status, record.analysis_id, record.test_name
        metric_map({'p_value': record.p_value, 'statistic': record.statistic, 'mean_difference': record.estimated_mean_difference}, 'statistical_result')
        warnings.extend(record.assumption_warnings)
        limitations.extend(record.limitations)
        if record.unavailable_reason:
            warnings.append(record.unavailable_reason)
        if record.confidence_interval.reason:
            warnings.append(record.confidence_interval.reason)
        if record.effect_size.reason:
            warnings.append(record.effect_size.reason)
        provenance = {'sources': record.source_ids, 'metadata': record.provenance, 'dependencies': record.dependency_versions}
        version, created = SourceVersion(kind='request_sha256', value=_digest(record.request.model_dump(mode='json'))), record.report_timestamp
        evidence.completeness = 'complete' if status == 'available' else 'incomplete'
        summary = record.summary
    elif isinstance(record, LatexTableResponse):
        kind, status, title = 'latex_table', 'generated', 'LaTeX results table'
        warnings.extend(record.warnings)
        evidence.missing_inputs = record.missing_metrics
        evidence.completeness = 'incomplete' if record.missing_metrics else 'complete'
        provenance = {'source_ids': record.source_ids, 'table_type': record.table_type, 'compiled': record.compiled}
        version, created = SourceVersion(kind='record_sha256', value=_digest(original)), record.generation_timestamp
        limitations.append('LaTeX generation does not establish successful compilation.')
        summary = f'Generated {record.table_type} table with {len(record.included_metrics)} metric columns/entries; {len(record.missing_metrics)} unavailable metrics. Not compiled.'
    else:
        kind, status, title, summary = 'workflow', record.status, 'Scientific workflow', record.summary
        evidence.completeness = 'complete' if status == 'completed' else 'incomplete'
        if record.error:
            warnings.append(f'{record.error.type}: {record.error.message}')
        limitations.append(record.description)
    if current_source_version is not None:
        current_source_version = SourceVersion.model_validate(current_source_version.model_dump())
    freshness = 'unknown'
    if version and current_source_version and version.kind == current_source_version.kind:
        freshness = 'matching' if version.value == current_source_version.value else 'stale'
    if freshness == 'stale':
        warnings.append('Historical evidence: the recorded source fingerprint differs from the current source.')
    if paths:
        warnings.append('Local paths are omitted from presentation; exact evidence remains in the authorized original record.')
    values.update(result_type=kind, source_id=source_id, source_version=version, current_source_version=current_source_version,
        freshness=freshness, status=status, title=title, summary=summary, metrics=[m.model_dump() for m in metrics],
        parameters=parameters, dataset_references=[d.model_dump() for d in datasets], artifacts=[a.model_dump() for a in artifacts],
        warnings=warnings, limitations=limitations, provenance=provenance, evidence=evidence.model_dump(), created_at=created)
    normalized = UnifiedScientificResult.model_validate(_public(values))
    from .next_actions import recommend_next_actions
    normalized.all_next_actions = recommend_next_actions(normalized)
    normalized.next_actions = [action for action in normalized.all_next_actions if action.eligible][:4]
    return normalized


def _specific(expected, record, **options):
    if not isinstance(record, expected):
        raise TypeError('Scientific record type does not match this normalization adapter')
    return normalize_scientific_result(record, **options)


def normalize_experiment_result(record, **options): return _specific(ExperimentResult, record, **options)
def normalize_replication_report(record, **options): return _specific(ReplicationReport, record, **options)
def normalize_iteration_result(record, **options): return _specific(OptimizationResult, record, **options)
def normalize_robustness_report(record, **options): return _specific(RobustnessReport, record, **options)
def normalize_statistics_report(record, **options): return _specific(StatisticalReport, record, **options)
def normalize_dataset_result(record, **options): return _specific((DatasetSummary, DatasetProcessingResult), record, **options)
def normalize_latex_table_result(record, **options): return _specific(LatexTableResponse, record, **options)


def scientific_response(record, *, action_context=None, action_limit=4, **options) -> dict:
    """Opt-in normalized {result, scientific}; legacy tool_response stays compatible."""
    from .integration import _text
    normalized = normalize_scientific_result(record, **options)
    from .next_actions import with_next_actions
    normalized = with_next_actions(normalized, action_context, limit=action_limit)
    lines = [_text(normalized.summary)]
    lines += ['Warning: ' + _text(item) for item in normalized.warnings]
    lines += ['Limitation: ' + _text(item) for item in normalized.limitations]
    return ScientificResponse(result='\n\n'.join(lines), scientific=normalized).model_dump(mode='json')
