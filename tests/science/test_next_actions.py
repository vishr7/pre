"""Eligibility is not authorization. No rule may execute, approve, or read files."""
import subprocess
from pathlib import Path

import pytest

from pre_science.experiment import ExperimentService
from pre_science.next_actions import ActionContext, recommend_next_actions, with_next_actions
from pre_science.results import SourceVersion, normalize_scientific_result
from pre_science.schemas import PublishedMetric
from test_results import experiment, reports


def action(result, name, context=None):
    return next(item for item in recommend_next_actions(result, context) if item.action_id == name)


def test_tables_use_only_actual_metrics_and_zero_is_valid():
    normalized = normalize_scientific_result(experiment())
    assert action(normalized, 'generate_latex_table').suggested_parameters['selected_metrics'] == ['score', 'zero']
    assert not action(normalize_scientific_result(experiment(metrics={})), 'generate_latex_table').eligible


def test_missing_references_and_review_confirmation():
    normalized = normalize_scientific_result(experiment())
    assert not action(normalized, 'compare_reference').eligible
    assert action(normalized, 'compare_reference').missing_inputs
    context = ActionContext(reviewed_references=[PublishedMetric(name='score', value=.3, absolute_tolerance=.1, relative_tolerance=0.)])
    assert not action(normalized, 'compare_reference', context).eligible
    context.references_reviewed = True
    assert action(normalized, 'compare_reference', context).eligible


def test_robustness_draft_is_separate_from_execution():
    normalized = normalize_scientific_result(experiment())
    assert not action(normalized, 'test_robustness').eligible
    context = ActionContext(authorized_configuration_reference='approved-source:1')
    suggested = action(normalized, 'test_robustness', context)
    assert suggested.eligible and suggested.requires_approval and not suggested.execution_authorized
    assert 'seeds' not in suggested.suggested_parameters


def test_dataset_preprocessing_is_review_only(reports):
    normalized = normalize_scientific_result(reports['dataset_inspection'])
    suggested = action(normalized, 'review_preprocessing')
    assert suggested.eligible and suggested.action_type == 'review'
    assert any('missing' in item for item in suggested.suggested_parameters['observed_issues'])
    assert 'transformations' not in suggested.suggested_parameters


def test_statistical_draft_requires_second_study_and_design_review(reports):
    first = normalize_scientific_result(reports['robustness'])
    other = reports['robustness'].model_copy(deep=True)
    other.study_id = 'second-study'
    for run in other.runs:
        run.execution.metrics['score'] += .01
    second = normalize_scientific_result(other)
    context = ActionContext(comparison_results=[second])
    assert not action(first, 'statistical_comparison', context).eligible
    context.comparison_design_reviewed = True
    proposed = action(first, 'statistical_comparison', context)
    assert proposed.eligible
    assert 'test' not in proposed.suggested_parameters and 'paired' not in proposed.suggested_parameters
    assert any('correspondence' in item for item in proposed.missing_inputs)
    assert not action(first, 'statistical_comparison', ActionContext(comparison_results=[first], comparison_design_reviewed=True)).eligible


def test_optimized_evaluation_is_new_and_approval_bound(reports):
    normalized = normalize_scientific_result(reports['optimization'])
    proposed = action(normalized, 'evaluate_optimized_configuration')
    assert proposed.eligible and proposed.requires_approval and not proposed.execution_authorized
    assert any('independent' in item for item in proposed.warnings)


def test_stale_source_blocks_followup_but_retains_historical_tables(reports):
    report = reports['replication']
    normalized = normalize_scientific_result(report, current_source_version=SourceVersion(kind='code_sha256', value='b'*64))
    assert normalized.freshness == 'stale'
    assert action(normalized, 'review_execution').eligible
    assert not action(normalized, 'test_robustness').eligible
    assert action(normalized, 'generate_latex_table').eligible


def test_default_order_and_visible_limit(reports):
    normalized = normalize_scientific_result(reports['replication'])
    result = with_next_actions(normalized, limit=3)
    assert len(result.next_actions) <= 3
    assert all(item.eligible for item in result.next_actions)
    assert result.all_next_actions[0].action_id == 'review_reproducibility_inputs'
    assert len(result.all_next_actions) == 9
    with pytest.raises(ValueError):
        with_next_actions(normalized, limit=6)


def test_figures_require_backend_availability_attestation():
    from pre_science.results import ResultArtifact
    normalized = normalize_scientific_result(experiment())
    reference = 'a'*32 + '-' + 'b'*32
    normalized.artifacts = [ResultArtifact(artifact_reference=reference, artifact_type='figure',
        mime_type='image/png', sha256='c'*64, size_bytes=10)]
    assert not action(normalized, 'inspect_figures').eligible
    proposed = action(normalized, 'inspect_figures', ActionContext(available_artifact_references=[reference]))
    assert proposed.eligible and proposed.suggested_parameters == {'artifact_references': [reference]}
    assert not proposed.execution_authorized


def test_rules_and_normalization_have_no_execution_or_io_side_effects(reports, monkeypatch):
    original = reports['replication'].model_dump_json()
    def forbidden(*args, **kwargs):
        raise AssertionError('No execution or file access is permitted')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(Path, 'read_text', forbidden)
    monkeypatch.setattr(ExperimentService, 'run', forbidden)
    normalized = normalize_scientific_result(reports['replication'])
    recommend_next_actions(normalized)
    assert reports['replication'].model_dump_json() == original
