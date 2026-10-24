"""Orchestrate experiments without choosing a transport or execution environment."""

import hashlib
import time
from datetime import datetime, timezone

from .contracts import ExecutionFailure, ExperimentExecutor
from .schemas import ExecutionError, ExecutionOutput, ExperimentRequest, ExperimentResult


class ExperimentService:
    def __init__(self, executor: ExperimentExecutor):
        self.executor = executor

    def run(self, specification: ExperimentRequest | dict) -> ExperimentResult:
        request = ExperimentRequest.model_validate(
            specification.model_dump() if isinstance(specification, ExperimentRequest) else specification
        )
        started = time.monotonic()
        submitted_at = datetime.now(timezone.utc).isoformat()
        try:
            output = self.executor.execute(request.model_copy(deep=True))
            output = ExecutionOutput.model_validate(output.model_dump())
        except ExecutionFailure as exc:
            output = ExecutionOutput(
                status='error', exit_code=-1,
                execution_time=time.monotonic() - started,
                error=ExecutionError(type='ExecutionFailure', message=str(exc)),
            )
        metadata = dict(output.execution_metadata)
        metadata.update(
            code_sha256=hashlib.sha256(request.code.encode('utf-8')).hexdigest(),
            submitted_at=submitted_at,
            orchestration_seconds=time.monotonic() - started,
            timeout_seconds=request.timeout_seconds,
            dataset_id=request.dataset_id,
            request_metadata=request.metadata,
        )
        return ExperimentResult(
            **output.model_dump(exclude={'execution_metadata'}),
            experiment_id=request.experiment_id, parameters=request.parameters,
            random_seed=request.random_seed, execution_metadata=metadata,
        )
