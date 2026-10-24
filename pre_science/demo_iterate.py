"""Trusted local Iris tuning demo, not a reproduction or independent test score.

The local executor below is for developer-authored fixtures only. Never connect
it to user/Gemini proposals: a subprocess is NOT a security sandbox.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .contracts import ExecutionFailure
from .experiment import ExperimentService
from .iterate import IterationService, optimization_digest
from .schemas import ExecutionError, ExecutionOutput, OptimizationRequest, ResearcherApproval


class _TrustedDemoExecutor:
    def execute(self, request):
        started = time.monotonic()
        # Fresh process per trial; no application credentials are inherited.
        allowed = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR',
                   'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'LANG', 'LC_ALL',
                   'MPLCONFIGDIR'}
        environment = {name: value for name, value in os.environ.items() if name.upper() in allowed}
        environment['PYTHONIOENCODING'] = 'utf-8'
        try:
            process = subprocess.run(
                [sys.executable, '-m', 'pre_science.worker'], input=request.model_dump_json(),
                text=True, encoding='utf-8', capture_output=True, timeout=request.timeout_seconds,
                cwd=Path(__file__).resolve().parents[1], env=environment, check=False,
            )
        except subprocess.TimeoutExpired:
            return ExecutionOutput(status='timeout', exit_code=124,
                                   execution_time=time.monotonic() - started,
                                   error=ExecutionError(type='Timeout', message='Trusted local trial exceeded its timeout'))
        try:
            output = ExecutionOutput.model_validate_json(process.stdout)
        except ValueError:
            raise ExecutionFailure('Trusted worker returned invalid structured output') from None
        if process.returncode != output.exit_code:
            raise ExecutionFailure('Trusted worker exit status did not match its output')
        return output


def iris_request() -> OptimizationRequest:
    return OptimizationRequest.model_validate({
        'study_id': 'local-iris-tree-demo', 'experiment_id': 'local-iris-tree',
        'base_parameters': {'validation_fraction': 0.3},
        'search_space': {
            'max_depth': {'type': 'int', 'low': 1, 'high': 6},
            'min_samples_split': {'type': 'int', 'low': 2, 'high': 10},
        },
        'objective_metric': 'accuracy', 'direction': 'maximize', 'n_trials': 6,
        'max_duration_seconds': 120, 'trial_timeout_seconds': 20, 'random_seed': 42,
        'code': '''
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score
assert "previous_trial_value" not in globals()
previous_trial_value = True
x, y = load_iris(return_X_y=True)
x_train, x_validation, y_train, y_validation = train_test_split(
    x, y, test_size=parameters["validation_fraction"], random_state=random_seed, stratify=y)
model = DecisionTreeClassifier(max_depth=parameters["max_depth"],
    min_samples_split=parameters["min_samples_split"], random_state=random_seed)
model.fit(x_train, y_train)
accuracy = float(accuracy_score(y_validation, model.predict(x_validation)))
report_metric("accuracy", accuracy)
print("Local Iris validation accuracy:", accuracy)
''',
    })


def main():
    request = iris_request()
    request.approval = ResearcherApproval(
        approved=True, approved_by='trusted-local-demo',
        specification_sha256=optimization_digest(request),
    )
    service = IterationService(ExperimentService(_TrustedDemoExecutor()))
    first, repeated = service.run(request), service.run(request)
    signature = lambda report: [(trial.suggested_parameters, trial.objective_value, trial.status)
                                for trial in report.trials]
    reproducible = signature(first) == signature(repeated)
    # Preserve evidence even when runtime failures make the repeat check fail.
    print(json.dumps({
        'description': 'Local Iris validation-set tuning; not a published reproduction or independent test result',
        'first_run': first.model_dump(mode='json'),
        'repeated_run': repeated.model_dump(mode='json'), 'reproducible': reproducible,
    }, indent=2, allow_nan=False))
    if first.status != 'completed' or repeated.status != 'completed':
        raise RuntimeError('Trusted demo did not complete both studies; inspect the emitted reports')
    if not reproducible:
        raise RuntimeError('Seeded trials differed; inspect the emitted execution and objective history')


if __name__ == '__main__':
    main()
