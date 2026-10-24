"""Mocked scheduling/statistics tests and real fresh-worker integration."""
import math
from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from scipy.stats import t

from pre_science.experiment import ExperimentService
from pre_science.plots import ArtifactStore
from pre_science.robustness import RobustnessRequest, RobustnessReport, RobustnessService, robustness_digest
from pre_science.schemas import ExecutionOutput, ExecutionError, ResearcherApproval


def proposal(**updates):
    return RobustnessRequest.model_validate(dict(study_id='study', experiment_id='source', code='pass',
        seeds=[1, 2, 3], metrics=['score']) | updates)


def approved(request):
    request.approval = ResearcherApproval(approved=True, approved_by='test', specification_sha256=robustness_digest(request))
    return request


def executor():
    mock = Mock()
    mock.execute.side_effect = lambda request: ExecutionOutput(status='success', exit_code=0,
        metrics={'score': float(request.random_seed)}, execution_metadata={'dependencies': {'numpy': 'fixture'}})
    return mock


@pytest.mark.parametrize('seeds', [[], [1], [1, 1], list(range(21)), [-1, 1], [1, 2**32], [True, 2], [1., 2]])
def test_invalid_seeds(seeds):
    with pytest.raises(ValidationError):
        RobustnessRequest(study_id='a', experiment_id='b', code='pass', seeds=seeds, metrics=['score'])


@pytest.mark.parametrize('update', [{'metrics': []}, {'metrics': [' ']}, {'metrics': ['x', 'x']},
    {'timeout_seconds': 0}, {'max_duration_seconds': 0}, {'parameters': {'x': float('nan')}},
    {'thresholds': {'score': {'max_std': -1.}}}, {'thresholds': {'score': {'max_range': float('inf')}}}])
def test_invalid_configuration(update):
    data = dict(study_id='s', experiment_id='e', code='pass', seeds=[1, 2], metrics=['score'])
    with pytest.raises(ValidationError):
        RobustnessRequest.model_validate(data | update)


def test_approval_and_all_specification_fields_are_bound():
    request = approved(proposal())
    mock = executor()
    service = RobustnessService(ExperimentService(mock))
    assert service.run(proposal()).status == 'approval_required'
    for key, value in [('code', 'print(1)'), ('parameters', {'x': 1}), ('seeds', [4, 5]),
                       ('metrics', ['other']), ('timeout_seconds', 2), ('max_duration_seconds', 10),
                       ('source', {'study': 'other'})]:
        modified = request.model_copy(deep=True)
        setattr(modified, key, value)
        assert service.run(modified).status == 'approval_required'
    mock.execute.assert_not_called()


def test_correct_statistics_seed_propagation_and_provenance():
    mock = executor()
    report = RobustnessService(ExperimentService(mock)).run(approved(proposal(confidence_interval=True)))
    summary = report.summaries['score']
    assert summary.values == [1., 2., 3.] and summary.seeds == [1, 2, 3]
    assert summary.mean == summary.median == 2.
    assert summary.sample_std == 1. and summary.minimum == 1. and summary.maximum == 3. and summary.range == 2.
    assert summary.standard_error == pytest.approx(1 / math.sqrt(3))
    margin = t.ppf(.975, 2) / math.sqrt(3)
    assert summary.confidence_interval_95 == pytest.approx([2 - margin, 2 + margin])
    calls = [call.args[0] for call in mock.execute.call_args_list]
    assert len({call.experiment_id for call in calls}) == 3
    assert [call.random_seed for call in calls] == [1, 2, 3]
    assert all(call.code == 'pass' and call.metadata['fresh_state_required'] for call in calls)
    assert all(run.execution.execution_metadata['code_sha256'] == report.code_sha256 for run in report.runs)
    assert len(report.dependency_versions) == 3
    assert RobustnessReport.model_validate_json(report.model_dump_json()) == report
    assert not summary.threshold_assessments


def test_failures_missing_metrics_and_thresholds():
    mock = Mock()
    mock.execute.side_effect = [ExecutionOutput(status='success', exit_code=0, metrics={'score': 2.}),
        ExecutionOutput(status='timeout', exit_code=124, error=ExecutionError(type='Timeout', message='timeout'), metrics={'score': 100.}),
        ExecutionOutput(status='success', exit_code=0)]
    report = RobustnessService(ExperimentService(mock)).run(approved(proposal(confidence_interval=True,
        thresholds={'score': {'max_std': 1., 'max_range': 0., 'min_successful_runs': 2}})))
    summary = report.summaries['score']
    assert report.completed_runs == 2 and report.failed_runs == 1
    assert report.status == 'completed_with_failures'
    assert summary.observation_count == 1 and summary.mean == 2.
    assert summary.sample_std is summary.confidence_interval_95 is None
    assert summary.threshold_assessments == {'max_std': None, 'max_range': True, 'min_successful_runs': False}
    assert report.runs[1].execution.status == 'timeout'
    assert report.runs[2].missing_metrics == ['score']


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), 'bad', True])
def test_invalid_output_and_all_failed(bad):
    mock = Mock()
    output = ExecutionOutput.model_construct(status='success', exit_code=0, metrics={'score': bad})
    mock.execute.return_value = output
    report = RobustnessService(ExperimentService(mock)).run(approved(proposal()))
    assert report.failed_runs == 3
    assert report.summaries['score'].mean is None
    assert report.summaries['score'].observation_count == 0


def test_infrastructure_errors_are_safe():
    mock = Mock()
    mock.execute.side_effect = RuntimeError('private path or credential')
    report = RobustnessService(ExperimentService(mock)).run(approved(proposal()))
    assert report.failed_runs == 3
    assert 'private path' not in report.model_dump_json()


def test_dataset_authorization_blocks_execution_and_is_approval_bound():
    mock = executor()
    request = approved(proposal(dataset={'dataset_id': 'private', 'description': 'approved data'}))
    service = RobustnessService(ExperimentService(mock))
    assert service.run(request).status == 'missing_inputs'
    mock.execute.assert_not_called()
    report = service.run(request, available_dataset_ids={'private'})
    assert report.dataset_provenance.dataset_id == 'private'
    assert report.runs[0].execution.execution_metadata['dataset_id'] == 'private'
    request.dataset.description = 'changed'
    assert service.run(request, available_dataset_ids={'private'}).status == 'approval_required'


def test_replication_origin_is_preserved_without_inherited_approval():
    from pre_science.demo_replicate import baseline_specification
    from pre_science.replicate import ReplicationService, specification_digest
    from pre_science.robustness import robustness_from_replication
    spec = baseline_specification()
    spec.approval = ResearcherApproval(approved=True, approved_by='test', specification_sha256=specification_digest(spec))
    mock = executor()
    original = ReplicationService(ExperimentService(mock)).run(spec)
    snapshot = original.model_dump_json()
    request = robustness_from_replication(original, study_id='new', seeds=[1, 2], metrics=['score'])
    assert request.code == spec.code and not request.approval.approved
    assert request.source['specification_sha256'] == original.specification_sha256
    assert original.model_dump_json() == snapshot


def test_optimization_origin_preserves_actual_best_parameters():
    from pre_science.demo_iterate import iris_request
    from pre_science.iterate import IterationService, optimization_digest
    from pre_science.robustness import robustness_from_optimization
    request = iris_request()
    request.n_trials = 1
    request.approval = ResearcherApproval(approved=True, approved_by='test', specification_sha256=optimization_digest(request))
    mock = Mock()
    mock.execute.return_value = ExecutionOutput(status='success', exit_code=0, metrics={'accuracy': .9})
    original = IterationService(ExperimentService(mock)).run(request)
    snapshot = original.model_dump_json()
    proposal = robustness_from_optimization(original, study_id='evaluation', seeds=[1, 2], metrics=['accuracy'])
    assert proposal.parameters == original.best_parameters
    assert not proposal.approval.approved and proposal.source['independent_test_evaluation'] is False
    assert original.model_dump_json() == snapshot


def test_budget_caps_timeout_and_retains_unattempted_seeds():
    class Clock:
        value = 0.
        def __call__(self):
            return self.value
    clock = Clock()
    mock = executor()
    def run(request):
        assert request.timeout_seconds == 2
        clock.value = 2.
        return ExecutionOutput(status='success', exit_code=0, metrics={'score': 1.})
    mock.execute.side_effect = run
    report = RobustnessService(ExperimentService(mock), clock=clock).run(approved(proposal(max_duration_seconds=2)))
    assert report.status == 'budget_exhausted' and report.unattempted_seeds == [2, 3]
    assert report.completed_runs == 1


def test_real_worker_seed_application_and_png_handoff(tmp_path):
    import hashlib
    from pre_science.trusted_demo import TrustedDemoExecutor
    from pre_science.integration import read_verified_artifact
    code = "import random\nimport numpy as np\nassert 'prior' not in globals()\nprior=True\nreport_metric('score', random.random()+np.random.random())"
    store = ArtifactStore(tmp_path / 'figures')
    service = RobustnessService(ExperimentService(TrustedDemoExecutor({hashlib.sha256(code.encode()).hexdigest()},
        work_root=tmp_path / 'workers', artifact_root=tmp_path / 'worker-figures')), artifact_store=store)
    request = approved(proposal(code=code, generate_figure=True))
    first, repeated = service.run(request), service.run(request)
    assert first.completed_runs == 3
    assert first.summaries['score'].values == repeated.summaries['score'].values
    assert len(first.artifacts) == 1
    assert read_verified_artifact(store, first.artifacts[0]).startswith(b'\x89PNG')
    assert all(run.execution.execution_metadata['seed_application']['applied_before_code'] == ['python.random', 'numpy.random.legacy'] for run in first.runs)
