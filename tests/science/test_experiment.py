"""Worker calls execute only trusted test literals. These are NOT isolation tests."""

import hashlib
import json
import subprocess
import sys
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from pre_science.contracts import ExecutionFailure
from pre_science.experiment import ExperimentService
from pre_science.schemas import ExecutionError, ExecutionOutput, ExperimentRequest, ExperimentResult
from pre_science.worker import run_worker


def request(code='print("hello")', **kwargs):
    return ExperimentRequest(experiment_id='test', code=code, **kwargs)


def test_valid_request():
    value = request(parameters={'nested': [1, True, None, {'x': 'y'}]}, dataset_id='dataset-1')
    assert value.timeout_seconds == 30
    assert value.random_seed == 0
    assert ExperimentRequest.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize('fields', [
    {'parameters': []}, {'parameters': {'bad': float('nan')}},
    {'parameters': {'bad': object()}}, {'random_seed': -1},
    {'random_seed': True}, {'random_seed': 2**32}, {'unknown': 'x'},
    {'metadata': {'bad': float('inf')}}, {'experiment_id': ' '},
])
def test_invalid_parameters(fields):
    with pytest.raises(ValidationError):
        ExperimentRequest.model_validate({'experiment_id': 'test', 'code': 'pass', **fields})


@pytest.mark.parametrize('timeout', [0, -1, 301, 1.5, True, '30'])
def test_invalid_timeout(timeout):
    with pytest.raises(ValidationError):
        request(timeout_seconds=timeout)


@pytest.mark.parametrize('timeout', [1, 300])
def test_timeout_boundaries(timeout):
    assert request(timeout_seconds=timeout).timeout_seconds == timeout


def test_trusted_worker_capture_and_explicit_metrics():
    result = run_worker(request('''
import sys
import numpy as np
data = np.array([10, 20, 30, 40, 50])
print("Mean:", float(data.mean()))
print("diagnostic", file=sys.stderr)
accuracy = 0.91
report_metric("mean", np.mean(data))
report_metric("std", float(np.std(data)))
'''))
    assert result.status == 'success'
    assert result.exit_code == 0
    assert result.stdout == 'Mean: 30.0\n'
    assert result.stderr == 'diagnostic\n'
    assert result.metrics == pytest.approx({'mean': 30.0, 'std': 14.142135623730951})
    assert 'accuracy' not in result.metrics
    assert result.execution_time >= 0
    assert result.execution_metadata['dependencies']['numpy']
    assert result.execution_metadata['python_version']


def test_no_implicit_metrics():
    assert run_worker(request('accuracy = 0.91')).metrics == {}


def test_scientific_stack_imports_in_trusted_worker():
    result = run_worker(request('''
import pandas as pd
from scipy import stats
from sklearn.metrics import mean_squared_error
import matplotlib
report_metric("mean", pd.Series([1, 2, 3]).mean())
report_metric("mse", mean_squared_error([1, 2], [1, 3]))
assert matplotlib.get_backend().lower() == "agg"
'''))
    assert result.status == 'success', result.error
    assert result.metrics == {'mean': 2.0, 'mse': 0.5}


@pytest.mark.parametrize(('code', 'kind'), [
    ('if :', 'SyntaxError'),
    ('print("before")\n1 / 0', 'ZeroDivisionError'),
    ('raise SystemExit(0)', 'SystemExit'),
    ('report_metric("x", float("nan"))', 'ValueError'),
    ('report_metric("x", True)', 'ValueError'),
    ('report_metric("x", 1)\nreport_metric("x", 2)', 'ValueError'),
])
def test_worker_errors(code, kind):
    result = run_worker(request(code))
    assert result.status == 'error'
    assert result.exit_code == 1
    assert result.error.type == kind
    assert kind in result.error.traceback
    if kind == 'ZeroDivisionError':
        assert result.stdout == 'before\n'


def test_orchestration_reproducibility_and_json():
    spec = request(parameters={'alpha': 0.1}, random_seed=42, metadata={'source': 'test'})
    executor = Mock()
    executor.execute.return_value = ExecutionOutput(
        status='success', exit_code=0, metrics={'score': 0.5},
        execution_metadata={'dependencies': {'numpy': 'test-worker-version'}},
    )
    result = ExperimentService(executor).run(spec)
    executor.execute.assert_called_once_with(spec)
    assert result.parameters == spec.parameters
    assert result.random_seed == 42
    assert result.execution_metadata['code_sha256'] == hashlib.sha256(spec.code.encode()).hexdigest()
    assert result.execution_metadata['request_metadata'] == {'source': 'test'}
    assert result.execution_metadata['dependencies']['numpy'] == 'test-worker-version'
    assert result.execution_metadata['submitted_at'].endswith('+00:00')
    assert ExperimentResult.model_validate_json(result.model_dump_json()) == result
    json.dumps(result.model_dump(), allow_nan=False)


def test_invalid_spec_never_reaches_executor():
    executor = Mock()
    with pytest.raises(ValidationError):
        ExperimentService(executor).run({'code': 'pass'})
    executor.execute.assert_not_called()


def test_transport_failure():
    executor = Mock()
    executor.execute.side_effect = ExecutionFailure('Container unavailable')
    result = ExperimentService(executor).run(request())
    assert result.status == 'error'
    assert result.error.type == 'ExecutionFailure'
    assert result.metrics == {}


def test_executor_timeout_is_preserved():
    executor = Mock()
    executor.execute.return_value = ExecutionOutput(
        status='timeout', exit_code=124, error=ExecutionError(type='Timeout', message='Deadline exceeded'),
    )
    assert ExperimentService(executor).run(request()).status == 'timeout'


def test_seed_and_parameter_injection():
    spec = request('''
import random
import numpy as np
report_metric("random", random.random() + np.random.random())
report_metric("parameter", parameters["alpha"])
''', parameters={'alpha': 2}, random_seed=42)
    assert run_worker(spec).metrics == run_worker(spec).metrics


@pytest.mark.parametrize('code', ['print("trusted CLI")', 'raise ValueError("trusted failure")'])
def test_worker_json_entrypoint(code):
    process = subprocess.run(
        [sys.executable, '-m', 'pre_science.worker'], input=request(code).model_dump_json(),
        text=True, capture_output=True, timeout=30, check=False,
    )
    result = ExecutionOutput.model_validate_json(process.stdout)
    assert result.exit_code == process.returncode
    assert result.status == ('success' if process.returncode == 0 else 'error')


def test_reject_inconsistent_executor_result():
    with pytest.raises(ValidationError):
        ExecutionOutput(status='success', exit_code=1)
