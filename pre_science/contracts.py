"""Person 4 implements this boundary using restricted container execution."""

from typing import Protocol

from .schemas import ExecutionOutput, ExperimentRequest


class ExecutionFailure(Exception):
    """Transport/container failure, rather than an experiment-code exception."""


class ExperimentExecutor(Protocol):
    def execute(self, request: ExperimentRequest) -> ExecutionOutput:
        """Enforce request.timeout_seconds externally; return captured worker output.

        On deadline expiry return status='timeout' and terminate the container.
        Raise ExecutionFailure for execution infrastructure failures.
        Scientific jobs must use fresh process/container and filesystem state;
        never route optimization trials to persistent notebook kernels.
        """
        ...
