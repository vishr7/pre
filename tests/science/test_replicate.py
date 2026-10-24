"""Mocked orchestration plus trusted real worker/dataset/figure integration."""

import hashlib
import io
import json
from unittest.mock import Mock

import pandas as pd
import pytest
from pydantic import ValidationError

from pre_science.data import DatasetArtifactStore, DatasetService
from pre_science.demo_replicate import baseline_specification
from pre_science.experiment import ExperimentService
from pre_science.plots import ArtifactStore
from pre_science.replicate import ReplicationService, compare_metric, specification_digest
from pre_science.schemas import (
    ExecutionError, ExecutionOutput, ExperimentRequest, ExperimentResult,
    ReplicationDataset, ReplicationReport, ReplicationSpecification, ResearcherApproval,
)
from pre_science.worker import run_worker


def approve(spec):
    spec.approval = ResearcherApproval(approved=True, approved_by='trusted-test',
                                      specification_sha256=specification_digest(spec))
    return spec


def mocked_service(metrics=None, *, status='success'):
    executor = Mock()
    executor.execute.return_value = ExecutionOutput(
        status=status, exit_code=0 if status == 'success' else 124 if status == 'timeout' else 1,
        metrics=metrics if metrics is not None else {'mean': 30.0, 'std': 14.142135623730951},
        stdout='actual mock output', execution_time=0.125,
        error=None if status == 'success' else ExecutionError(type='TestFailure', message='Failed execution'),
        execution_metadata={'dependencies': {'numpy': 'worker-version'}},
    )
    return ReplicationService(ExperimentService(executor)), executor


def test_specification_validation_and_roundtrip():
    proposal = baseline_specification()
    assert proposal.approval.approved is False
    assert ReplicationSpecification.model_validate_json(proposal.model_dump_json()) == proposal
    assert proposal.paper.publication_year is None
    assert proposal.paper.authors is None


@pytest.mark.parametrize('approval', [None, {'approved': True},
    {'approved': True, 'approved_by': 'test', 'specification_sha256': '0' * 64}])
def test_missing_or_unbound_approval_prevents_execution(approval):
    proposal = baseline_specification()
    if approval is not None:
        proposal.approval = ResearcherApproval.model_validate(approval)
    service, executor = mocked_service()
    report = service.run(proposal)
    executor.execute.assert_not_called()
    assert report.status == 'approval_required'
    assert report.execution_status == report.numerical_assessment == 'not_executed'
    assert report.specification == proposal
    assert report.reproduced_metrics == {} and report.code_sha256 is None
    assert all(item.agrees is None for item in report.comparisons)


def test_editing_approved_proposal_requires_new_approval():
    proposal = approve(baseline_specification())
    proposal.code += '\nprint("changed")'
    service, executor = mocked_service()
    assert service.run(proposal).status == 'approval_required'
    executor.execute.assert_not_called()


def test_approved_calls_injected_experiment_service_and_preserves_evidence():
    proposal = approve(baseline_specification())
    experiments = Mock()
    experiments.run.return_value = ExperimentResult(
        experiment_id=proposal.experiment_id, parameters=proposal.parameters, random_seed=42,
        status='success', exit_code=0, metrics={'mean': 30.0, 'std': 14.142135623730951},
        execution_metadata={'code_sha256': 'f' * 64, 'dependencies': {'numpy': 'worker'}},
    )
    report = ReplicationService(experiments).run(proposal.model_dump(mode='json'))
    experiments.run.assert_called_once()
    request, = experiments.run.call_args.args
    assert isinstance(request, ExperimentRequest)
    assert request.code == proposal.code
    assert request.random_seed == 42
    assert request.parameters == proposal.parameters
    assert report.code_sha256 == 'f' * 64
    assert report.dependency_versions == {'numpy': 'worker'}
    assert report.numerical_assessment == 'all_comparable_agree'
    assert report.methodology_completeness == 'fully_specified'
    assert 'local demonstration' in ' '.join(report.warnings)


@pytest.mark.parametrize(('reference', 'actual', 'atol', 'rtol', 'agrees'), [
    (1.0, 1.0, 0.0, 0.0, True), (1.0, 1.25, .25, 0.0, True),
    (10.0, 10.25, 0.0, .03125, True), (10.0, 10.5, .125, .03125, False),
    (0.0, .125, .125, .5, True), (0.0, .125, 0.0, 100.0, False),
    (-10.0, -10.25, 0.0, .03125, True), (-10.0, 10.0, 0.0, 0.0, False),
    (1e308, -1e308, 1e308, 0.0, False),
])
def test_numerical_rule(reference, actual, atol, rtol, agrees):
    result = compare_metric('x', reference, actual, absolute_tolerance=atol, relative_tolerance=rtol)
    assert result.agrees is agrees
    assert result.status == ('match' if agrees else 'different')
    if reference == 0:
        assert result.relative_difference is result.percentage_difference is None
    if reference == 1e308:
        assert result.absolute_difference is None and result.warnings
    json.dumps(result.model_dump(), allow_nan=False)


def test_relative_percentage_and_no_rounding():
    result = compare_metric('x', -2.0, -2.5, absolute_tolerance=0.0, relative_tolerance=0.0)
    assert result.absolute_difference == .5
    assert result.relative_difference == .25
    assert result.percentage_difference == 25.0
    result = compare_metric('x', 1.0, 1.0000000000000002, absolute_tolerance=0.0, relative_tolerance=0.0)
    assert result.agrees is False


@pytest.mark.parametrize(('published', 'reproduced'), [
    (float('nan'), 1.0), (1.0, float('inf')), (float('-inf'), 1.0),
    ('1.0', 1.0), (1.0, '1.0'), (True, 1.0), (1.0, None),
])
def test_invalid_comparison_values_are_unavailable_and_json_safe(published, reproduced):
    result = compare_metric('x', published, reproduced, absolute_tolerance=0.0, relative_tolerance=0.0)
    assert result.status == 'unavailable' and result.agrees is None and result.reason
    json.dumps(result.model_dump(), allow_nan=False)


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True, '0.1'])
@pytest.mark.parametrize('field', ['absolute_tolerance', 'relative_tolerance'])
def test_invalid_tolerances_are_rejected(value, field):
    options = {'absolute_tolerance': 0.0, 'relative_tolerance': 0.0, field: value}
    with pytest.raises(ValidationError):
        compare_metric('x', 1.0, 1.0, **options)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 'not numeric'])
def test_invalid_published_values_are_rejected_before_execution(value):
    proposal = baseline_specification().model_dump()
    proposal['published_metrics'][0]['value'] = value
    service, executor = mocked_service()
    with pytest.raises(ValidationError):
        service.run(proposal)
    executor.execute.assert_not_called()


def test_missing_and_additional_metrics_do_not_fabricate_results():
    service, _ = mocked_service({'mean': 30.0, 'extra': 7.0})
    report = service.run(approve(baseline_specification()))
    assert report.numerical_assessment == 'all_comparable_agree'
    assert report.all_published_metrics_agree is None
    assert report.additional_metrics == {'extra': 7.0}
    assert report.comparisons[1].status == 'unavailable'
    assert report.comparisons[1].reproduced_value is None
    assert 'std' not in report.reproduced_metrics


def test_no_metrics_and_different_metrics():
    service, _ = mocked_service({})
    report = service.run(approve(baseline_specification()))
    assert report.numerical_assessment == 'no_comparable_metrics'
    assert report.reproduced_metrics == {}
    service, _ = mocked_service({'mean': 31.0, 'std': 14.142135623730951})
    report = service.run(approve(baseline_specification()))
    assert report.numerical_assessment == 'some_metrics_differ'
    assert report.all_published_metrics_agree is False


@pytest.mark.parametrize('field', ['code', 'parameters', 'random_seed', 'dataset_required'])
def test_missing_execution_inputs_never_trigger_defaults(field):
    proposal = baseline_specification()
    setattr(proposal, field, None)
    service, executor = mocked_service()
    report = service.run(approve(proposal))
    executor.execute.assert_not_called()
    assert report.status == 'missing_inputs'
    assert report.methodology_completeness == 'insufficient_information'
    assert report.missing_inputs


def test_optional_methodology_missing_and_unknown_conditions_are_partial():
    proposal = baseline_specification()
    proposal.algorithm = proposal.published_parameters = proposal.published_random_seed = None
    proposal.limitations.original_conditions_known = None
    service, _ = mocked_service()
    report = service.run(approve(proposal))
    assert report.status == 'completed'
    assert report.methodology_completeness == 'partially_specified'
    assert 'Algorithm or method' in report.missing_information


def test_assumptions_and_substitution_prevent_full_assessment():
    proposal = baseline_specification()
    proposal.limitations.assumptions = ['Using a local proxy dataset']
    proposal.limitations.unavailable_datasets = ['Original source data']
    proposal.limitations.substituted_parameters = ['Changed regularization']
    service, _ = mocked_service()
    report = service.run(approve(proposal))
    assert report.all_published_metrics_agree is True
    assert report.methodology_completeness == 'approximate_reconstruction'
    assert report.assumptions == ['Using a local proxy dataset']


def test_parameter_and_seed_changes_are_detected_without_declared_substitution():
    proposal = baseline_specification()
    proposal.random_seed = 7
    proposal.parameters = {'values': [1, 2, 3]}
    service, _ = mocked_service()
    assert service.run(approve(proposal)).methodology_completeness == 'approximate_reconstruction'


@pytest.mark.parametrize('status', ['error', 'timeout'])
def test_execution_failures_never_become_successful_comparisons(status):
    service, _ = mocked_service(status=status)
    report = service.run(approve(baseline_specification()))
    assert report.status == report.numerical_assessment == 'execution_failed'
    assert report.execution_status == status
    assert report.execution.error is not None
    assert report.reproduced_metrics['mean'] == 30.0  # Actual partial output retained.
    assert all(item.status == 'execution_failed' and item.agrees is None for item in report.comparisons)
    assert report.all_published_metrics_agree is None


def test_dataset_reference_does_not_establish_availability():
    proposal = baseline_specification()
    proposal.dataset_required = True
    proposal.dataset = ReplicationDataset(dataset_id='authorized-study')
    proposal.required_asset_ids = ['model-weights']
    service, executor = mocked_service()
    report = service.run(approve(proposal))
    assert report.status == 'missing_inputs'
    executor.execute.assert_not_called()
    report = service.run(approve(proposal), available_dataset_ids={'authorized-study'},
                         available_asset_ids={'model-weights'})
    assert report.status == 'completed'
    assert report.dataset_provenance.dataset_id == 'authorized-study'


def test_real_worker_dataset_provenance_figures_and_report_json(tmp_path):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    (inputs / 'data.csv').write_text('x,label\n10,A\n20,A\n30,B\n40,B\n50,B\n')
    dataset_store = DatasetArtifactStore(tmp_path / 'csv-output')
    datasets = DatasetService(inputs, {'study': 'data.csv'}, artifact_store=dataset_store)
    processed = datasets.process({'dataset_id': 'study', 'transformations': [
        {'operation': 'select_columns', 'columns': ['x']},
    ]})
    data = dataset_store.retrieve(processed.artifact.artifact_id)
    assert hashlib.sha256(data).hexdigest() == processed.artifact.sha256
    assert pd.read_csv(io.BytesIO(data)).shape == (5, 1)
    mounted = tmp_path / 'approved-input.csv'
    mounted.write_bytes(data)  # Simulated authorized mount for trusted test code only.
    figures = ArtifactStore(tmp_path / 'figures')

    class TrustedTestExecutor:
        def execute(self, request):
            return run_worker(request, artifact_store=figures)

    proposal = baseline_specification()
    proposal.dataset_required = True
    proposal.dataset = ReplicationDataset(
        dataset_id='study', description='Five known values from a trusted fixture',
        original_sha256=processed.provenance.source_sha256, processed=processed.artifact.to_reference(),
        transformations=processed.transformations,
    )
    proposal.parameters = {'dataset_path': str(mounted)}
    proposal.code = '''
import pandas as pd
import matplotlib.pyplot as plt
x = pd.read_csv(parameters["dataset_path"])["x"]
report_metric("mean", float(x.mean()))
report_metric("std", float(x.std(ddof=0)))
print("trusted dataset executed")
plt.figure(figsize=(3, 2))
plt.plot(x)
'''
    report = ReplicationService(ExperimentService(TrustedTestExecutor())).run(
        approve(proposal), available_dataset_ids={'study'})
    assert report.all_published_metrics_agree is True
    assert report.execution.stdout == 'trusted dataset executed\n'
    assert report.code_sha256 == hashlib.sha256(proposal.code.encode()).hexdigest()
    assert report.execution.random_seed == report.random_seed == 42
    assert report.execution.parameters == proposal.parameters
    assert report.execution_duration >= 0
    assert report.dependency_versions['numpy']
    assert report.dataset_provenance.processed.sha256 == processed.artifact.sha256
    assert report.execution.execution_metadata['request_metadata']['processed_dataset']['sha256'] == processed.artifact.sha256
    assert len(report.artifacts) == 1
    artifact = report.artifacts[0]
    assert artifact.experiment_id == proposal.experiment_id
    assert hashlib.sha256(figures.retrieve(artifact.artifact_id)).hexdigest() == artifact.sha256
    assert ReplicationReport.model_validate_json(report.model_dump_json()) == report
    json.dumps(report.model_dump(), allow_nan=False)
    assert 'does not prove' in report.summary
