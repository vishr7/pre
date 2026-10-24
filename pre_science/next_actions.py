"""Deterministic suggestions only. No execution, approval, I/O or test selection."""
from pydantic import Field

from .results import NextAction, UnifiedScientificResult
from .schemas import Model, PublishedMetric


class ActionContext(Model):
    authorized_configuration_reference: str | None = Field(default=None, pattern=r'^[A-Za-z0-9][A-Za-z0-9:._-]{0,255}$')
    reviewed_references: list[PublishedMetric] = Field(default_factory=list)
    references_reviewed: bool = False
    available_artifact_references: list[str] = Field(default_factory=list)
    comparison_results: list[UnifiedScientificResult] = Field(default_factory=list)
    comparison_design_reviewed: bool = False


def recommend_next_actions(result: UnifiedScientificResult, context: ActionContext | None = None) -> list[NextAction]:
    if not isinstance(result, UnifiedScientificResult):
        raise TypeError('Next actions require a normalized scientific result')
    result = UnifiedScientificResult.model_validate(result.model_dump())
    context = ActionContext.model_validate(context.model_dump()) if context is not None else ActionContext()
    actions = []
    source_ids = [result.result_id] if result.result_id is not None else []
    def add(identifier, title, kind, eligible, reason, *, required=(), missing=(), approval=False, suggested=None, warnings=()):
        actions.append(NextAction(action_id=identifier, title=title, description=reason, action_type=kind,
            eligible=bool(eligible), reason=reason, required_inputs=list(required), missing_inputs=list(missing),
            requires_approval=approval, source_result_ids=source_ids, suggested_parameters=suggested or {}, warnings=list(warnings)))
    evidence = result.evidence
    missing = list(evidence.missing_inputs)
    if result.result_type == 'experiment' and not (evidence.configuration_available or context.authorized_configuration_reference):
        missing.append('Authorized source code/configuration reference; execution output alone does not contain source code')
    add('review_reproducibility_inputs', 'Review missing reproducibility inputs', 'review', bool(missing),
        'Review explicitly missing or unverified inputs; unknown information is not a verified experimental failure.' if missing else 'No specific missing reproducibility inputs are recorded.',
        missing=missing, suggested={'items_to_review': missing})
    failed = evidence.execution_status in ('error', 'timeout', 'not_executed') or evidence.completeness == 'incomplete'
    add('review_execution', 'Review failed or incomplete evidence', 'review', failed or result.freshness == 'stale',
        'Review status, failures, missing measurements and source freshness before further interpretation.' if failed or result.freshness == 'stale' else 'No recorded failure, incompleteness or stale source requires this review.')
    add('review_preprocessing', 'Review preprocessing suggestions', 'review', bool(evidence.preprocessing_issues),
        'Data-quality findings support a non-destructive preprocessing review; no transformation is selected or applied.' if evidence.preprocessing_issues else 'No missing-value or duplicate issue is recorded.',
        suggested={'observed_issues': evidence.preprocessing_issues}, warnings=['Transformations require researcher review; avoid fitting preprocessing on evaluation data.'])
    figure_refs = [item.artifact_reference for item in result.artifacts if item.artifact_type == 'figure']
    retrievable = [ref for ref in figure_refs if ref in context.available_artifact_references]
    add('inspect_figures', 'Inspect recorded figures', 'view', bool(retrievable),
        'The backend has attested availability of these opaque references; no URLs are generated.' if retrievable else 'No figure reference has backend-confirmed retrieval availability.',
        required=['Authorized artifact retrieval'], missing=[] if retrievable else ['Backend availability confirmation for recorded figures'],
        suggested={'artifact_references': retrievable}, warnings=['Availability is caller-attested; this function does not access storage or authorize retrieval.'])
    measured = [item.name for item in result.metrics if item.value is not None and item.role == 'measurement']
    supports_tables = result.result_type in ('experiment', 'replication')
    add('generate_latex_table', 'Generate a LaTeX results table', 'generate', supports_tables and bool(measured),
        'Recorded measurements can populate the existing table formatter, retaining status and limitations.' if supports_tables and measured else 'The current table formatter requires measured ExperimentResult or ReplicationReport records; this result has no supported measured input.',
        required=['Authorized original record', 'Caption and label'],
        missing=[] if supports_tables and measured else ['Supported original record with actual measured metrics'],
        suggested={'selected_metrics': list(dict.fromkeys(measured))} if supports_tables and measured else {})
    reviewed = evidence.reviewed_reference_metrics
    if context.references_reviewed:
        reviewed = reviewed + [metric.name for metric in context.reviewed_references]
    comparable = sorted(set(measured) & set(reviewed))
    add('compare_reference', 'Compare with reviewed reference values', 'compare', bool(comparable) and evidence.execution_status == 'success',
        'Actual measurements and reviewed reference names overlap; use the original typed values and configured tolerances.' if comparable else 'Supply reviewed reference values and tolerances for the recorded metrics; none are inferred.',
        required=['Successful measured execution', 'Reviewed reference values and tolerances'],
        missing=[] if comparable and evidence.execution_status == 'success' else ['Reviewed matching references or successful execution'],
        suggested={'metrics': comparable}, warnings=['A tolerance match does not establish faithful scientific reproduction.'])
    peers = []
    for other in context.comparison_results:
        if other.result_id is not None and other.result_id == result.result_id:
            continue
        # Equal study/source identity or identical evidence is not a second method.
        if other.source_id == result.source_id or other.evidence.observations == evidence.observations:
            continue
        common = sorted({item.metric for item in evidence.observations if item.complete and len(item.values) >= 2}
                        & {item.metric for item in other.evidence.observations if item.complete and len(item.values) >= 2})
        if common:
            peers.append((other, common))
    add('statistical_comparison', 'Draft a statistical comparison', 'draft', bool(peers) and context.comparison_design_reviewed,
        'Two distinct studies have repeated observations and caller-reviewed compatible units/design. Draft only: explicitly choose metric, test, hypothesis and pairing.' if peers and context.comparison_design_reviewed else 'Provide a second complete observation series and review metric units, evaluation design and comparability.',
        required=['Two compatible observation series', 'User-selected test and alternative', 'Independence and pairing review'],
        missing=['Test selection', 'Hypothesis/independence review', 'Explicit condition correspondence before any paired test'] + ([] if context.comparison_design_reviewed else ['Units/design compatibility review']) if peers else ['Second compatible observation series'],
        suggested={'candidate_source_ids': [other.source_id for other, common in peers], 'common_metrics': sorted(set(name for other, common in peers for name in common))},
        warnings=['Matching seeds do not establish pairing; require corresponding experimental conditions.', 'Shared datasets and optimization selection can invalidate independent-inference assumptions.'])
    configuration = evidence.configuration_available or bool(context.authorized_configuration_reference)
    stale = result.freshness == 'stale'
    add('test_robustness', 'Draft a multi-seed evaluation', 'draft', configuration and not stale and result.result_type in ('experiment', 'replication', 'optimization', 'robustness'),
        'An authorized/configured source is available to draft a separate multi-seed request; execution is not authorized.' if configuration and not stale else 'Supply an authorized code/configuration reference and resolve stale-source differences before drafting.',
        required=['Code/configuration reference', 'Researcher-selected seeds and metrics', 'Fresh approval', 'Restricted executor'],
        missing=['Seeds, settings and fresh approval must be reviewed before execution'] if configuration and not stale else ['Authorized current configuration'],
        approval=True, suggested={'available_metrics': list(dict.fromkeys(item.name for item in result.metrics))},
        warnings=['Do not run untrusted code through the host notebook runtime.'])
    add('evaluate_optimized_configuration', 'Draft a separate evaluation of the selected best configuration', 'draft', evidence.best_configuration_available and not stale,
        'The study contains an actual best observed configuration; create a new evaluation with separate approval.' if evidence.best_configuration_available and not stale else 'An actual selected best configuration and non-stale source are required.',
        required=['Selected actual configuration', 'Evaluation design/data', 'Fresh approval', 'Restricted executor'],
        missing=['Evaluation design and fresh approval'] if evidence.best_configuration_available else ['Successful selected best configuration'],
        approval=True, warnings=['Optimization scores are selection evidence, not independent test performance.'])
    return actions


def with_next_actions(result: UnifiedScientificResult, context: ActionContext | None = None, *, limit=4):
    """Return a copy with the full rule list and 0–5 eligible visible suggestions."""
    if type(limit) is not int or not 0 <= limit <= 5:
        raise ValueError('Visible action limit must be an integer from 0 through 5')
    result = UnifiedScientificResult.model_validate(result.model_dump())
    result.all_next_actions = recommend_next_actions(result, context)
    result.next_actions = [action for action in result.all_next_actions if action.eligible][:limit]
    return result
