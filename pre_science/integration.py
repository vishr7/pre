"""Pure adapters for existing frontend/backend contracts; no routes or execution."""

import hashlib
import html

from .schemas import (
    ArtifactVerification, DatasetArtifact, DatasetProcessingResult, DatasetSummary,
    ExperimentRequest, ExperimentResult, FigureArtifact, OptimizationRequest,
    OptimizationResult, RepeatabilityAssessment, ReplicationReport,
    ReplicationSpecification, ScientificWorkflowReport,
)


class ArtifactIntegrityError(ValueError):
    pass


def read_verified_artifact(store, artifact: FigureArtifact | DatasetArtifact) -> bytes:
    """Read through the existing store and verify the persisted bytes."""
    data = store.retrieve(artifact.artifact_reference)
    if len(data) != artifact.size_bytes or hashlib.sha256(data).hexdigest() != artifact.sha256:
        raise ArtifactIntegrityError('Artifact bytes do not match the recorded size and SHA-256')
    return data


def artifact_verification(store, artifact):
    data = read_verified_artifact(store, artifact)
    return ArtifactVerification(artifact_id=artifact.artifact_id, mime_type=artifact.mime_type,
                                size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def validate_ai_proposal(kind: str, payload: dict):
    models = {'experiment': ExperimentRequest, 'replicate': ReplicationSpecification, 'iterate': OptimizationRequest}
    if kind not in models:
        raise ValueError('Unsupported scientific proposal type')
    proposal = models[kind].model_validate(payload)
    approval = getattr(proposal, 'approval', None)
    if approval is not None and (approval.approved or approval.approved_by or approval.specification_sha256):
        raise ValueError('AI proposals cannot supply researcher authorization')
    return proposal


def compare_optimization_runs(first: OptimizationResult, repeated: OptimizationResult) -> RepeatabilityAssessment:
    parameters = [trial.suggested_parameters for trial in first.trials] == [trial.suggested_parameters for trial in repeated.trials]
    objectives = [trial.objective_value for trial in first.trials] == [trial.objective_value for trial in repeated.trials]
    statuses = [trial.status for trial in first.trials] == [trial.status for trial in repeated.trials]
    failures = [[trial.error.type for trial in report.trials if trial.error] for report in (first, repeated)]
    requests = first.request_sha256 == repeated.request_sha256
    complete = all(report.status == 'completed' and report.failed_trial_count == 0
                   and report.successful_trial_count == report.request.n_trials for report in (first, repeated))
    reproducible = requests and parameters and objectives and statuses and complete
    if not requests:
        reason = 'Requests differ; these are not repeat runs of the same approved configuration.'
    elif failures[0] or failures[1]:
        reason = 'Execution/objective failures are present; inspect per-trial errors before attributing numerical variation.'
    elif not complete:
        reason = 'At least one study is incomplete or stopped.'
    elif not parameters:
        reason = 'Suggested parameter sequences differ.'
    elif not objectives:
        reason = 'Successful trials produced different objective values.'
    else:
        reason = 'All requested successful trials match in parameters and objective values.'
    return RepeatabilityAssessment(
        requests_match=requests, parameters_match=parameters, objectives_match=objectives,
        statuses_match=statuses, reproducible=reproducible,
        first_failure_types=failures[0], repeated_failure_types=failures[1], reason=reason,
    )


def _text(value):
    # Escape untrusted text before inserting it into Markdown prose/tables.
    text = html.escape(str(value), quote=True).replace('\n', ' ').replace('\r', ' ')
    for character in '\\`*_{}[]()#+-.!|':
        text = text.replace(character, '\\' + character)
    return text


def tool_response(report) -> dict:
    """Compatibility with POST /api/tools/:mode's {result: Markdown} contract.

    The full machine-readable report is preserved as `scientific`. This does not
    authorize returning internal logs to unauthenticated callers.
    """
    if isinstance(report, ExperimentResult):
        lines = [f'Execution: **{report.status}**.', f'Figures/artifacts: {len(report.artifacts)}.']
        lines += [f'- {_text(name)}: {value!r}' for name, value in report.metrics.items()]
    elif isinstance(report, ReplicationReport):
        lines = [_text(report.summary), 'Numerical agreement does not establish scientific fidelity.']
        lines += [f'- {_text(item.name)}: reference {item.published_value!r}, actual {item.reproduced_value!r}; {item.status}.'
                  for item in report.comparisons]
        lines += [f'- Missing information: {_text(item)}' for item in report.missing_information]
        lines += [f'- Warning: {_text(item)}' for item in report.warnings]
    elif isinstance(report, OptimizationResult):
        lines = [f'Optimization: **{report.status}**.',
                 f'Successful trials: {report.successful_trial_count}; failed: {report.failed_trial_count}.',
                 f'Best observed objective: {report.best_objective_value!r}.',
                 'Optimized outcomes are separate from faithful reproduction claims.']
    elif isinstance(report, DatasetSummary):
        lines = [f'Dataset: {report.row_count} rows, {report.column_count} columns; {report.duplicate_rows} duplicate rows.']
        lines += [f'- {_text(column.name)}: {column.missing_count} missing values.' for column in report.columns]
    elif isinstance(report, DatasetProcessingResult):
        lines = [f'Processing: **{report.status}**.']
        lines += [f'- {entry.operation}: {entry.rows_before} → {entry.rows_after} rows; {entry.status}.'
                  for entry in report.transformations]
    elif isinstance(report, ScientificWorkflowReport):
        lines = [_text(report.description), _text(report.summary)]
    else:
        from .robustness import RobustnessReport
        from .statistics import StatisticalReport
        from .latex_tables import LatexTableResponse
        if not isinstance(report, (RobustnessReport, StatisticalReport, LatexTableResponse)):
            raise TypeError('Unsupported scientific report type')
        report = type(report).model_validate(report.model_dump(warnings=False))
        if isinstance(report, RobustnessReport):
            lines = [f'Robustness: **{report.status}**. Successful executions: {report.completed_runs}; failed: {report.failed_runs}.']
            lines += [f'- {_text(name)}: n={item.observation_count}, mean={item.mean!r}, sample SD={item.sample_std!r}.'
                      for name, item in report.summaries.items()]
            lines += ['Warning: ' + _text(item) for item in report.warnings]
        elif isinstance(report, StatisticalReport):
            lines = [_text(report.summary)]
            lines += ['Warning: ' + _text(item) for item in report.assumption_warnings]
            lines += ['Limitation: ' + _text(item) for item in report.limitations]
        else:
            lines = [f'Generated {report.table_type} table. Not compiled.']
            lines += ['Warning: ' + _text(item) for item in report.warnings]
    return {'result': '\n\n'.join(lines), 'scientific': report.model_dump(mode='json')}
