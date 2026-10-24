"""Real sequential scientific workflow plus explicitly mocked failure diagnostics."""

import hashlib
import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from pre_science.contracts import ExecutionFailure
from pre_science.demo_end_to_end import EXPERIMENT_CODE, run_demo
from pre_science.integration import (
    ArtifactIntegrityError, compare_optimization_runs, read_verified_artifact,
    tool_response, validate_ai_proposal,
)
from pre_science.plots import ArtifactStore
from pre_science.schemas import ExecutionError, ExperimentRequest, ScientificWorkflowReport
from pre_science.trusted_demo import TrustedDemoExecutor
from pre_science.worker import run_worker


@pytest.fixture(scope='module')
def workflow(tmp_path_factory):
    root = tmp_path_factory.mktemp('real-scientific-workflow')
    report = run_demo(root, n_trials=2)
    assert report.status == 'completed', report.model_dump_json()
    return root, report


def test_real_csv_processing_execution_and_comparison(workflow):
    root, report = workflow
    assert report.dataset_inspection.row_count == 15
    assert report.dataset_inspection.duplicate_rows == 1
    assert report.dataset_processing.final_summary.row_count == 12
    assert len(report.dataset_processing.transformations) == 3
    assert report.baseline.metrics['validation_rows'] == 4
    assert report.replication.all_published_metrics_agree is True
    assert report.replication.specification.paper.source_kind == 'local_baseline'
    assert all(item.reproduced_value == report.baseline.metrics[item.name]
               for item in report.replication.comparisons)
    assert hashlib.sha256((root / 'approved-input.csv').read_bytes()).hexdigest() == report.dataset_processing.artifact.sha256


def test_real_optimization_repeatability_and_isolated_process_evidence(workflow):
    root, report = workflow
    assert report.repeatability.reproducible
    for study in (report.optimization, report.repeated_optimization):
        assert study.successful_trial_count == 2
        assert study.failed_trial_count == 0
        assert study.best_objective_value == max(t.objective_value for t in study.trials)
        assert all(t.execution_metadata['code_sha256'] == hashlib.sha256(EXPERIMENT_CODE.encode()).hexdigest()
                   for t in study.trials)
        assert all(t.execution_metadata['dataset_id'] == 'local-study' for t in study.trials)
        assert all(t.execution_metadata['trusted_demo_transport']['fresh_working_directory'] for t in study.trials)
        assert all(isinstance(t.execution_metadata['process_id'], int) for t in study.trials)
    assert not list((root / 'workers').glob('job-*'))


def test_real_artifacts_preserve_bytes_metadata(workflow):
    root, report = workflow
    assert len(report.artifacts_verified) == 7  # CSV + six actual execution figures
    assert len({a.artifact_id for a in report.artifacts_verified}) == 7
    store = ArtifactStore(root / 'figure-artifacts')
    for artifact in report.baseline.artifacts:
        assert read_verified_artifact(store, artifact).startswith(b'\x89PNG\r\n\x1a\n')
        assert artifact.width > 0 and artifact.height > 0
    # Cleanup is tested separately by the existing artifact suite; reports remain usable.


def test_full_report_json_and_frontend_adapter_keep_evidence(workflow):
    _, report = workflow
    payload = tool_response(report)
    restored = ScientificWorkflowReport.model_validate(json.loads(json.dumps(payload['scientific'], allow_nan=False)))
    assert restored == report
    assert isinstance(payload['result'], str)
    assert tool_response(report.replication)['scientific'] == report.replication.model_dump(mode='json')
    assert tool_response(report.optimization)['scientific']['trials']


def test_ai_proposals_reject_latex_and_missing_fields_without_execution():
    with pytest.raises(ValidationError):
        validate_ai_proposal('experiment', {'summary': 'proposal', 'edits': [], 'source': 'LaTeX'})
    with pytest.raises(ValidationError):
        validate_ai_proposal('replicate', {})
    valid = validate_ai_proposal('experiment', {'experiment_id': 'proposal', 'code': 'pass'})
    assert valid.code == 'pass'


def test_ai_cannot_self_authorize(workflow):
    _, report = workflow
    with pytest.raises(ValueError, match='authorization'):
        validate_ai_proposal('iterate', report.optimization.request.model_dump(mode='json'))


def test_artifact_integrity_detects_same_size_corruption(workflow):
    _, report = workflow
    artifact = report.baseline.artifacts[0]
    fake_store = Mock()
    fake_store.retrieve.return_value = b'x' * artifact.size_bytes
    with pytest.raises(ArtifactIntegrityError):
        read_verified_artifact(fake_store, artifact)


def test_mocked_failure_is_not_reported_as_numerical_nondeterminism(workflow):
    _, report = workflow
    failed = report.optimization.model_copy(deep=True)
    failed.trials[0].status = 'timeout'
    failed.trials[0].objective_value = None
    failed.trials[0].error = ExecutionError(type='Timeout', message='controlled test')
    failed.failed_trial_count = 1
    failed.successful_trial_count = 1
    assessment = compare_optimization_runs(failed, report.repeated_optimization)
    assert not assessment.reproducible
    assert assessment.first_failure_types == ['Timeout']
    assert 'Execution/objective failures' in assessment.reason


@pytest.mark.parametrize('raises', [False, True])
def test_real_worker_restores_matplotlib_settings_even_after_error(tmp_path, raises):
    import matplotlib
    old = matplotlib.rcParams['figure.figsize'][:]
    code = "import matplotlib as mpl\nmpl.rcParams['figure.figsize'] = [1, 1]\n"
    if raises:
        code += "raise ValueError('controlled failure')"
    result = run_worker(ExperimentRequest(experiment_id='style-state', code=code), artifact_store=ArtifactStore(tmp_path))
    assert result.status == ('error' if raises else 'success')
    assert matplotlib.rcParams['figure.figsize'] == old


def test_trusted_transport_rejects_unregistered_code_before_execution(tmp_path):
    executor = TrustedDemoExecutor(set(), work_root=tmp_path)
    with pytest.raises(ExecutionFailure):
        executor.execute(ExperimentRequest(experiment_id='unregistered', code='pass'))
    assert not list(tmp_path.glob('job-*'))
