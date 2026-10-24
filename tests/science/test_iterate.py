"""Bounded Optuna orchestration tests and trusted fresh-worker integration."""

import hashlib
import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from pre_science.demo_iterate import _TrustedDemoExecutor, iris_request
from pre_science.demo_replicate import baseline_specification
from pre_science.experiment import ExperimentService
from pre_science.iterate import IterationService, optimization_digest, optimization_from_replication
from pre_science.replicate import ReplicationService, specification_digest
from pre_science.schemas import (
    ExecutionError, ExecutionOutput, ExperimentResult, OptimizationRequest,
    OptimizationResult, ReplicationDataset, ResearcherApproval,
)


def proposal(**updates):
    data = {
        'study_id': 'test-study', 'experiment_id': 'source-experiment',
        'code': 'report_metric("score", parameters["x"])', 'base_parameters': {'fixed': 7},
        'search_space': {'x': {'type': 'int', 'low': 1, 'high': 10}},
        'objective_metric': 'score', 'direction': 'maximize', 'n_trials': 4,
        'max_duration_seconds': 60, 'trial_timeout_seconds': 10, 'random_seed': 42,
    }
    data.update(updates)
    return OptimizationRequest.model_validate(data)


def approve(request):
    request.approval = ResearcherApproval(approved=True, approved_by='trusted-test',
                                         specification_sha256=optimization_digest(request))
    return request


def executor_for_parameters():
    executor = Mock()
    executor.execute.side_effect = lambda request: ExecutionOutput(
        status='success', exit_code=0, execution_time=.1,
        metrics={'score': float(request.parameters['x'])},
        execution_metadata={'dependencies': {'numpy': 'test-worker-version'}},
    )
    return executor


@pytest.mark.parametrize('space', [
    {'type': 'int', 'low': 1, 'high': 5}, {'type': 'int', 'low': 1, 'high': 5, 'step': 2},
    {'type': 'int', 'low': 1, 'high': 32, 'log': True},
    {'type': 'float', 'low': .001, 'high': .1},
    {'type': 'float', 'low': .001, 'high': .1, 'log': True},
    {'type': 'categorical', 'choices': [1, 2, 3]},
])
def test_supported_spaces_and_seeded_reproducibility(space):
    request = approve(proposal(search_space={'x': space}))
    executor = executor_for_parameters()
    service = IterationService(ExperimentService(executor))
    first, second = service.run(request), service.run(request)
    assert first.status == second.status == 'completed'
    assert [trial.suggested_parameters for trial in first.trials] == [trial.suggested_parameters for trial in second.trials]
    assert [trial.objective_value for trial in first.trials] == [trial.objective_value for trial in second.trials]
    for trial in first.trials:
        value = trial.suggested_parameters['x']
        assert value in space['choices'] if space['type'] == 'categorical' else space['low'] <= value <= space['high']


def test_string_categorical_and_fresh_request_parameter_injection():
    request = approve(proposal(search_space={'criterion': {'type': 'categorical', 'choices': ['gini', 'entropy']}}))
    executor = Mock()
    executor.execute.return_value = ExecutionOutput(status='success', exit_code=0, metrics={'score': .9})
    report = IterationService(ExperimentService(executor)).run(request)
    calls = [call.args[0] for call in executor.execute.call_args_list]
    assert len({id(call) for call in calls}) == 4
    assert len({call.experiment_id for call in calls}) == 4
    assert all(call.code == request.code and call.random_seed == 42 for call in calls)
    assert all(call.parameters['fixed'] == 7 for call in calls)
    assert all(call.parameters['criterion'] in ('gini', 'entropy') for call in calls)
    assert all(call.metadata['fresh_state_required'] is True for call in calls)
    assert report.successful_trial_count == 4


@pytest.mark.parametrize('space', [
    {'type': 'int', 'low': 5, 'high': 1}, {'type': 'int', 'low': 0, 'high': 5, 'log': True},
    {'type': 'int', 'low': 1, 'high': 5, 'step': 2, 'log': True},
    {'type': 'int', 'low': 1, 'high': 4, 'step': 2},
    {'type': 'float', 'low': .1, 'high': .001},
    {'type': 'float', 'low': 0, 'high': 1, 'log': True},
    {'type': 'float', 'low': 0, 'high': float('inf')},
    {'type': 'float', 'low': -1e13, 'high': 1},
    {'type': 'categorical', 'choices': []},
    {'type': 'categorical', 'choices': [True, 1]},
    {'type': 'categorical', 'choices': [float('nan')]},
    {'type': 'categorical', 'choices': [10**20]},
    {'type': 'callable', 'function': 'eval'},
])
def test_invalid_spaces_are_pydantic_errors(space):
    with pytest.raises(ValidationError):
        proposal(search_space={'x': space})


@pytest.mark.parametrize('update', [
    {'search_space': {}}, {'base_parameters': {'x': 1}},
    {'n_trials': 0}, {'n_trials': 51}, {'n_trials': True},
    {'max_duration_seconds': 0}, {'max_duration_seconds': 901},
    {'trial_timeout_seconds': 301}, {'random_seed': -1},
    {'base_parameters': {'bad': float('nan')}},
])
def test_request_bounds_and_conflicts(update):
    with pytest.raises(ValidationError):
        proposal(**update)


def test_missing_approval_stale_approval_and_json_roundtrip():
    executor = executor_for_parameters()
    service = IterationService(ExperimentService(executor))
    request = proposal()
    assert service.run(request).status == 'approval_required'
    approve(request)
    request.search_space['x'].high = 9
    assert service.run(request).status == 'approval_required'
    executor.execute.assert_not_called()
    approve(request)
    restored = OptimizationRequest.model_validate_json(request.model_dump_json())
    assert optimization_digest(restored) == optimization_digest(request)
    report = service.run(restored)
    assert OptimizationResult.model_validate_json(report.model_dump_json()) == report
    json.dumps(report.model_dump(), allow_nan=False)


@pytest.mark.parametrize('direction', ['minimize', 'maximize'])
def test_best_trial_selection_and_best_so_far(direction):
    executor = executor_for_parameters()
    request = approve(proposal(direction=direction))
    report = IterationService(ExperimentService(executor)).run(request)
    values = [trial.objective_value for trial in report.trials]
    target = min(values) if direction == 'minimize' else max(values)
    assert report.best_objective_value == target
    assert report.best_trial_number == values.index(target)
    assert report.best_parameters == report.trials[values.index(target)].parameters
    assert report.best_suggested_parameters == report.trials[values.index(target)].suggested_parameters
    assert [point.best_so_far for point in report.history] == [
        (min(values[:i+1]) if direction == 'minimize' else max(values[:i+1])) for i in range(len(values))]
    assert report.best_parameters['fixed'] == 7


def test_missing_metric_and_stdout_are_not_objectives():
    executor = Mock()
    executor.execute.return_value = ExecutionOutput(
        status='success', exit_code=0, metrics={}, stdout='score = 0.99', execution_time=.2)
    report = IterationService(ExperimentService(executor)).run(approve(proposal()))
    assert report.status == 'failed'
    assert report.failed_trial_count == 4 and report.successful_trial_count == 0
    assert report.best_parameters is report.best_objective_value is None
    assert all(trial.error.type == 'MissingObjective' for trial in report.trials)
    assert all(trial.execution_status == 'success' and trial.objective_value is None for trial in report.trials)
    assert all(trial.execution.stdout == 'score = 0.99' for trial in report.trials)


@pytest.mark.parametrize('objective', [float('nan'), float('inf'), 'invalid', True])
def test_malformed_objectives_fail_without_non_json_values(objective, recwarn):
    experiments = Mock()
    def invalid_result(request):
        return ExperimentResult.model_construct(
            experiment_id=request.experiment_id, parameters=request.parameters, random_seed=42,
            status='success', exit_code=0, metrics={'score': objective})
    experiments.run.side_effect = invalid_result
    report = IterationService(experiments).run(approve(proposal(n_trials=1)))
    assert report.status == 'failed'
    assert report.trials[0].error.type == 'InvalidExecutionResult'
    assert report.trials[0].objective_value is None
    assert report.trials[0].execution is None
    json.dumps(report.model_dump(), allow_nan=False)
    assert not recwarn


def test_partial_errors_timeouts_and_invalid_parameter_combinations_continue():
    executor = Mock()
    executor.execute.side_effect = [
        ExecutionOutput(status='error', exit_code=1,
                        error=ExecutionError(type='ValueError', message='Invalid parameter combination')),
        ExecutionOutput(status='timeout', exit_code=124,
                        error=ExecutionError(type='Timeout', message='Worker timeout')),
        ExecutionOutput(status='success', exit_code=0, metrics={'score': .8}),
        ExecutionOutput(status='success', exit_code=0, metrics={'score': .9}),
    ]
    report = IterationService(ExperimentService(executor)).run(approve(proposal()))
    assert report.status == 'completed'
    assert report.successful_trial_count == report.failed_trial_count == 2
    assert report.best_objective_value == .9
    assert [trial.execution_status for trial in report.trials] == ['error', 'timeout', 'success', 'success']
    assert [point.best_so_far for point in report.history] == [None, None, .8, .9]


def test_infrastructure_exception_is_sanitized_and_remaining_trials_continue():
    executor = Mock()
    executor.execute.side_effect = [RuntimeError('fake-sensitive-value'),
                                   ExecutionOutput(status='success', exit_code=0, metrics={'score': .5})]
    report = IterationService(ExperimentService(executor)).run(approve(proposal(n_trials=2)))
    assert report.failed_trial_count == report.successful_trial_count == 1
    assert 'fake-sensitive-value' not in report.model_dump_json()


def test_study_budget_caps_trial_timeouts_and_keeps_partial_results():
    class Clock:
        now = 0.0
        def __call__(self):
            return self.now
    clock = Clock()
    executor = Mock()
    def execute(request):
        clock.now += 3  # Deliberately ignore timeout to model a noncompliant executor.
        return ExecutionOutput(status='success', exit_code=0, metrics={'score': 1.0})
    executor.execute.side_effect = execute
    report = IterationService(ExperimentService(executor), clock=clock).run(
        approve(proposal(max_duration_seconds=5, n_trials=4)))
    assert report.status == 'time_limit' and report.successful_trial_count == 2
    assert [call.args[0].timeout_seconds for call in executor.execute.call_args_list] == [5, 2]
    assert report.study_duration == 6.0  # Scheduler cannot forcibly terminate a running call.
    assert report.best_objective_value == 1.0


def test_backend_stop_keeps_history_and_can_prevent_all_execution():
    executor = executor_for_parameters()
    service = IterationService(ExperimentService(executor))
    report = service.run(approve(proposal()), should_stop=lambda: executor.execute.call_count >= 1)
    assert report.status == 'stopped' and len(report.trials) == 1
    executor.reset_mock()
    report = service.run(approve(proposal()), should_stop=lambda: True)
    assert report.status == 'stopped' and report.trials == []
    assert report.best_objective_value is None
    executor.execute.assert_not_called()


def test_budget_expiring_during_sampling_never_executes(monkeypatch):
    import pre_science.iterate as iterate
    class Clock:
        now = 0.0
        def __call__(self):
            return self.now
    clock = Clock()
    original = iterate._suggest
    def slow_suggest(*args):
        values = original(*args)
        clock.now = 2.0
        return values
    monkeypatch.setattr(iterate, '_suggest', slow_suggest)
    executor = executor_for_parameters()
    report = IterationService(ExperimentService(executor), clock=clock).run(
        approve(proposal(max_duration_seconds=1)))
    assert report.status == 'time_limit'
    assert report.trials[0].execution_status == 'not_executed'
    assert report.trials[0].error.type == 'StudyTimeLimit'
    executor.execute.assert_not_called()


def test_parameter_names_do_not_override_execution_controls():
    request = approve(proposal(search_space={
        'timeout_seconds': {'type': 'int', 'low': 100, 'high': 200}}, n_trials=1))
    executor = Mock()
    executor.execute.return_value = ExecutionOutput(status='success', exit_code=0, metrics={'score': 0.0})
    report = IterationService(ExperimentService(executor)).run(request)
    execution_request = executor.execute.call_args.args[0]
    assert execution_request.timeout_seconds == 10
    assert execution_request.parameters['timeout_seconds'] >= 100
    assert report.best_objective_value == 0.0


def test_missing_dataset_and_assets_prevent_execution_and_provenance_is_preserved():
    request = proposal(dataset={'dataset_id': 'study', 'original_sha256': 'a' * 64},
                       required_asset_ids=['weights'])
    executor = executor_for_parameters()
    service = IterationService(ExperimentService(executor))
    assert service.run(approve(request)).status == 'missing_inputs'
    executor.execute.assert_not_called()
    report = service.run(request, available_dataset_ids={'study'}, available_asset_ids={'weights'})
    assert report.dataset_provenance.original_sha256 == 'a' * 64
    assert report.code_sha256 == hashlib.sha256(request.code.encode()).hexdigest()
    for trial in report.trials:
        assert trial.execution_metadata['dataset_id'] == 'study'
        assert trial.execution_metadata['request_metadata']['source_experiment_id'] == request.experiment_id
        assert trial.execution_metadata['code_sha256'] == report.code_sha256
        assert trial.execution_metadata['dependencies'] == {'numpy': 'test-worker-version'}


def test_starting_from_replication_keeps_baseline_and_requires_separate_approval():
    replication_executor = Mock()
    replication_executor.execute.return_value = ExecutionOutput(
        status='success', exit_code=0, metrics={'mean': 30.0, 'std': 14.142135623730951})
    source = baseline_specification()
    source.approval = ResearcherApproval(approved=True, approved_by='trusted-test',
                                         specification_sha256=specification_digest(source))
    reproduced = ReplicationService(ExperimentService(replication_executor)).run(source)
    snapshot = reproduced.model_dump_json()
    request = optimization_from_replication(
        reproduced, study_id='from-replication', search_space={'ddof': {'type': 'int', 'low': 0, 'high': 1}},
        objective_metric='std', direction='minimize', n_trials=2, max_duration_seconds=30)
    assert request.approval.approved is False
    assert 'ddof' not in request.base_parameters
    assert request.source_replication.baseline_metrics == reproduced.reproduced_metrics
    assert request.source_replication.code_sha256 == reproduced.code_sha256
    assert reproduced.model_dump_json() == snapshot
    service = IterationService(ExperimentService(replication_executor))
    assert service.run(request).status == 'approval_required'
    report = service.run(approve(request))
    assert report.best_objective_value == reproduced.reproduced_metrics['std']
    assert any('not faithful reproductions' in warning for warning in report.warnings)


def test_real_iris_training_through_fresh_worker_processes():
    request = iris_request()
    request.n_trials = 2
    request.code += '\nimport matplotlib.pyplot as plt\nplt.figure(figsize=(2, 2))\nplt.plot([1, 2])'
    report = IterationService(ExperimentService(_TrustedDemoExecutor())).run(approve(request))
    assert report.status == 'completed'
    assert report.successful_trial_count == 2 and report.failed_trial_count == 0
    assert 0 <= report.best_objective_value <= 1
    assert all('Local Iris validation accuracy:' in trial.execution.stdout for trial in report.trials)
    assert all(trial.execution_metadata['dependencies']['scikit-learn'] for trial in report.trials)
    assert all(len(trial.artifacts) == 1 for trial in report.trials)
    assert all(trial.artifacts[0].experiment_id == trial.execution_id for trial in report.trials)
    json.dumps(report.model_dump(), allow_nan=False)
