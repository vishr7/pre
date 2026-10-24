"""Container worker entrypoint. NOT a sandbox; deadlines require an external supervisor.

Direct Python calls are only for trusted developer-authored tests/demos.
"""

import contextlib
import io
import math
import os
import platform
import random
import sys
import time
import traceback
from importlib.metadata import PackageNotFoundError, version

from .schemas import ExecutionError, ExecutionOutput, ExperimentRequest
from .plots import ArtifactStore, FigureLimits, capture_figures


def run_worker(request: ExperimentRequest, *, artifact_store: ArtifactStore | None = None,
               figure_limits: FigureLimits | None = None) -> ExecutionOutput:
    """Execute one approved request inside an externally restricted worker."""
    request = ExperimentRequest.model_validate(request.model_dump())
    started = time.monotonic()
    stdout, stderr = io.StringIO(), io.StringIO()
    metrics = {}
    error = None
    dependencies = {}
    artifacts, artifact_errors = [], []
    plt = None

    def report_metric(name, value):
        import numbers
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValueError('Metric name must be nonblank text of at most 128 characters')
        if isinstance(value, (bool,)) or not isinstance(value, numbers.Real):
            raise ValueError('Metrics must be finite real numbers')
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Metrics must be finite real numbers')
        if name in metrics:
            raise ValueError(f'Metric already reported: {name}')
        metrics[name] = number

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            os.environ['MPLBACKEND'] = 'Agg'
            import matplotlib
            matplotlib.use('Agg', force=True)
            import matplotlib.pyplot as plt
            plt.close('all')  # Each job owns a fresh figure state.
            import numpy as np
            random.seed(request.random_seed)
            np.random.seed(request.random_seed)
            namespace = {
                '__name__': '__main__', 'parameters': request.parameters,
                'random_seed': request.random_seed, 'dataset_id': request.dataset_id,
                'report_metric': report_metric,
            }
            exec(compile(request.code, '<experiment>', 'exec'), namespace)
        except BaseException as exc:
            error = ExecutionError(
                type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc(),
            )
        finally:
            if plt is not None:
                try:
                    if plt.get_fignums():
                        artifacts, artifact_errors = capture_figures(
                            request.experiment_id,
                            artifact_store if artifact_store is not None else ArtifactStore(),
                            figure_limits if figure_limits is not None else FigureLimits(),
                        )
                except Exception as exc:
                    artifact_errors.append(f'Figure capture: {type(exc).__name__}: {exc}')
                finally:
                    plt.close('all')
    for package in ('numpy', 'pandas', 'scipy', 'scikit-learn', 'matplotlib', 'optuna', 'pydantic'):
        try:
            dependencies[package] = version(package)
        except PackageNotFoundError:
            dependencies[package] = None
    return ExecutionOutput(
        status='error' if error else 'success', exit_code=1 if error else 0,
        stdout=stdout.getvalue(), stderr=stderr.getvalue(), metrics=metrics,
        artifacts=artifacts,
        error=error, execution_time=time.monotonic() - started,
        execution_metadata={'python_version': platform.python_version(), 'dependencies': dependencies,
                            'artifact_errors': artifact_errors},
    )


def main():
    """One JSON request on stdin, one JSON response on stdout; no HTTP endpoint."""
    if sys.argv[1:] == ['--demo']:
        from .experiment import ExperimentService

        class TrustedDemoExecutor:
            def execute(self, request):
                return run_worker(request)

        # Fixed developer-authored code only. Never connect this executor to requests.
        request = ExperimentRequest(experiment_id='trusted-demo', random_seed=42, code='''
import numpy as np
data = np.array([10, 20, 30, 40, 50])
mean = float(np.mean(data))
std = float(np.std(data))
print("Mean:", mean)
print("Standard deviation:", std)
report_metric("mean", mean)
report_metric("std", std)
''')
        result = ExperimentService(TrustedDemoExecutor()).run(request)
        print(result.model_dump_json(indent=2))
        return result.exit_code
    try:
        request = ExperimentRequest.model_validate_json(sys.stdin.read())
        output = run_worker(request)
    except Exception as exc:
        output = ExecutionOutput(status='error', exit_code=1,
                                 error=ExecutionError(type=type(exc).__name__, message=str(exc)))
    print(output.model_dump_json())
    return output.exit_code


if __name__ == '__main__':
    raise SystemExit(main())
