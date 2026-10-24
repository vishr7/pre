"""Sequential Optuna scheduling through the existing scientific execution boundary."""

from collections.abc import Callable, Collection
from datetime import datetime, timezone
import hashlib
import json
import math
import time
from uuid import uuid4

import optuna
from optuna.trial import TrialState
from pydantic import ValidationError

from .experiment import ExperimentService
from .schemas import (
    ExecutionError, ExperimentRequest, ExperimentResult, OptimizationPoint,
    OptimizationRequest, OptimizationResult, OptimizationTrial, ReplicationOrigin, ReplicationReport,
)


class _StudyBudgetExpired(Exception):
    pass


def optimization_digest(request: OptimizationRequest) -> str:
    request = OptimizationRequest.model_validate(request.model_dump())
    encoded = json.dumps(request.model_dump(mode='json', exclude={'approval'}),
                         sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(b'pre-iterate-v1\n' + encoded).hexdigest()


def optimization_from_replication(report: ReplicationReport, *, study_id, search_space,
                                 objective_metric, direction, n_trials, max_duration_seconds,
                                 trial_timeout_seconds=30) -> OptimizationRequest:
    """Build an UNAPPROVED optimization proposal without changing the source report.

    Selecting varied keys explicitly removes them from fixed parameters. The
    original measured metrics remain separately identified as baseline evidence.
    """
    report = ReplicationReport.model_validate(report.model_dump())
    execution = report.execution
    if execution is None or execution.status != 'success' or report.specification.code is None:
        raise ValueError('Optimization requires a successfully executed source reconstruction')
    if hashlib.sha256(report.specification.code.encode()).hexdigest() != report.code_sha256:
        raise ValueError('Source code does not match the executed code hash')
    return OptimizationRequest(
        study_id=study_id, experiment_id=report.experiment_id, code=report.specification.code,
        base_parameters={key: value for key, value in execution.parameters.items() if key not in search_space},
        dataset=report.dataset_provenance, required_asset_ids=report.specification.required_asset_ids,
        search_space=search_space, objective_metric=objective_metric, direction=direction,
        n_trials=n_trials, max_duration_seconds=max_duration_seconds,
        trial_timeout_seconds=trial_timeout_seconds, random_seed=execution.random_seed,
        source_replication=ReplicationOrigin(
            experiment_id=report.experiment_id, specification_sha256=report.specification_sha256,
            code_sha256=report.code_sha256, baseline_metrics=execution.metrics,
            report_timestamp=report.report_timestamp,
        ),
    )


def _suggest(trial, search_space):
    suggested = {}
    # Order is canonical, so JSON object insertion order does not alter suggestions.
    for name, space in sorted(search_space.items()):
        if space.type == 'int':
            suggested[name] = trial.suggest_int(name, space.low, space.high, step=space.step, log=space.log)
        elif space.type == 'float':
            suggested[name] = trial.suggest_float(name, space.low, space.high, log=space.log)
        else:
            suggested[name] = trial.suggest_categorical(name, space.choices)
    return suggested


class IterationService:
    def __init__(self, experiment_service: ExperimentService, *, clock: Callable[[], float] = time.monotonic):
        self.experiments = experiment_service
        self.clock = clock

    def run(self, specification: OptimizationRequest | dict, *,
            available_dataset_ids: Collection[str] = (), available_asset_ids: Collection[str] = (),
            should_stop: Callable[[], bool] | None = None) -> OptimizationResult:
        request = OptimizationRequest.model_validate(
            specification.model_dump() if isinstance(specification, OptimizationRequest) else specification)
        start = self.clock()
        started_at = datetime.now(timezone.utc).isoformat()
        digest = optimization_digest(request)
        code_hash = hashlib.sha256(request.code.encode('utf-8')).hexdigest()
        run_id = uuid4().hex
        trials, history, missing = [], [], []
        best, error = None, None
        warnings = [
            'Best observed values describe only this bounded search, not a global optimum.',
            'The executor must enforce deadlines and fresh process/container state for every trial.',
        ]
        if request.source_replication:
            warnings.append('Optimized results use changed parameters and are not faithful reproductions of the source conditions.')
        if request.dataset and request.dataset.dataset_id not in available_dataset_ids:
            missing.append('Backend-confirmed availability of the exact approved dataset')
        if any(asset not in available_asset_ids for asset in request.required_asset_ids):
            missing.append('Backend-confirmed availability of required assets')
        approved = (request.approval.approved and request.approval.approved_by is not None
                    and request.approval.specification_sha256 == digest)
        if not approved:
            status = 'approval_required'
        elif missing:
            status = 'missing_inputs'
        else:
            status = 'completed'
            study = optuna.create_study(
                direction=request.direction, study_name=f'pre-iterate-{run_id}',
                sampler=optuna.samplers.TPESampler(seed=request.random_seed),
            )
            for _ in range(request.n_trials):
                if should_stop is not None and should_stop():
                    status = 'stopped'
                    break
                remaining = request.max_duration_seconds - (self.clock() - start)
                if remaining < 1:
                    status = 'time_limit'
                    break
                trial_start = self.clock()
                trial = study.ask()
                execution_id = f'iterate-{run_id}-t{trial.number}'
                execution, objective, trial_error = None, None, None
                suggested, parameters = {}, dict(request.base_parameters)
                execution_status = 'not_executed'
                try:
                    suggested = _suggest(trial, request.search_space)
                    parameters.update(suggested)
                    remaining = request.max_duration_seconds - (self.clock() - start)
                    if remaining < 1:
                        raise _StudyBudgetExpired
                    experiment = ExperimentRequest(
                        experiment_id=execution_id, code=request.code, parameters=parameters,
                        random_seed=request.random_seed,
                        timeout_seconds=min(request.trial_timeout_seconds, math.floor(remaining)),
                        dataset_id=request.dataset.dataset_id if request.dataset else None,
                        metadata={
                            'study_id': request.study_id, 'optimization_run_id': run_id,
                            'source_experiment_id': request.experiment_id, 'trial_number': trial.number,
                            'optimization_request_sha256': digest, 'fresh_state_required': True,
                            'optimization_dataset': request.dataset.model_dump(mode='json') if request.dataset else None,
                            'processed_dataset': request.dataset.processed.model_dump(mode='json')
                            if request.dataset and request.dataset.processed else None,
                            'source_replication': request.source_replication.model_dump(mode='json')
                            if request.source_replication else None,
                        },
                    )
                    raw = self.experiments.run(experiment)
                    # Validate malformed executor output without serializing its raw
                    # values into Pydantic warning logs.
                    execution = ExperimentResult.model_validate(raw.model_dump(warnings=False))
                    if execution.experiment_id != execution_id:
                        raise ValueError('Unrelated execution result')
                    execution_status = execution.status
                    if execution.status != 'success':
                        trial_error = execution.error
                    elif request.objective_metric not in execution.metrics:
                        trial_error = ExecutionError(type='MissingObjective', message='Requested metric was not explicitly reported')
                    else:
                        # ExperimentResult enforces numeric finite metrics. No stdout/variable guessing.
                        objective = execution.metrics[request.objective_metric]
                except _StudyBudgetExpired:
                    status = 'time_limit'
                    trial_error = ExecutionError(type='StudyTimeLimit', message='Study deadline reached before execution')
                except ValidationError:
                    execution, execution_status = None, 'invalid_result'
                    trial_error = ExecutionError(type='InvalidExecutionResult', message='Experiment result failed structured numerical validation')
                except Exception:
                    execution, execution_status = None, 'invalid_result'
                    trial_error = ExecutionError(type='TrialExecutionFailure', message='Trial execution or result collection failed')
                success = trial_error is None and objective is not None
                study.tell(trial, objective if success else None,
                           state=TrialState.COMPLETE if success else TrialState.FAIL)
                record = OptimizationTrial(
                    trial_number=trial.number, execution_id=execution_id,
                    suggested_parameters=suggested, parameters=parameters,
                    objective_value=objective if success else None, status='success' if success else 'failed',
                    execution_status=execution_status,
                    execution_duration=execution.execution_time if execution else None,
                    trial_duration=max(0.0, self.clock() - trial_start), error=trial_error,
                    execution_metadata=execution.execution_metadata if execution else {},
                    artifacts=execution.artifacts if execution else [], execution=execution,
                )
                trials.append(record)
                if success and (best is None or (objective < best.objective_value if request.direction == 'minimize'
                                                 else objective > best.objective_value)):
                    best = record
                history.append(OptimizationPoint(
                    trial_number=trial.number, objective_value=record.objective_value,
                    best_so_far=best.objective_value if best else None, status=record.status,
                ))
                if status == 'time_limit':
                    break
            if self.clock() - start >= request.max_duration_seconds:
                status = 'time_limit'
            if status == 'completed' and best is None:
                status = 'failed'
                error = ExecutionError(type='AllTrialsFailed', message='No trial produced a valid objective value')
        return OptimizationResult(
            request=request, request_sha256=digest, study_id=request.study_id,
            experiment_id=request.experiment_id, run_id=run_id, status=status,
            objective_metric=request.objective_metric, direction=request.direction,
            trials=trials, history=history,
            successful_trial_count=sum(trial.status == 'success' for trial in trials),
            failed_trial_count=sum(trial.status == 'failed' for trial in trials),
            best_trial_number=best.trial_number if best else None,
            best_parameters=best.parameters if best else None,
            best_suggested_parameters=best.suggested_parameters if best else None,
            best_objective_value=best.objective_value if best else None,
            study_duration=max(0.0, self.clock() - start), code_sha256=code_hash,
            random_seed=request.random_seed, dataset_provenance=request.dataset,
            source_replication=request.source_replication,
            sampler_metadata={'name': 'TPESampler', 'seed': request.random_seed,
                              'optuna_version': optuna.__version__, 'execution_mode': 'sequential'},
            missing_inputs=missing, warnings=warnings, error=error, started_at=started_at,
            report_timestamp=datetime.now(timezone.utc).isoformat(),
        )
