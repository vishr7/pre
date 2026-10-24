"""Sequential multi-seed evaluation through the existing execution boundary."""

from collections.abc import Callable, Collection
from datetime import datetime, timezone
import hashlib
import json
import math
import time
from uuid import uuid4

import numpy as np
from pydantic import Field, JsonValue, model_validator
from scipy.stats import t

from .experiment import ExperimentService
from .plots import ArtifactStore, FigureLimits, capture_figures
from .schemas import (ExecutionError, ExperimentRequest, ExperimentResult, FigureArtifact,
                      Model, OptimizationResult, ReplicationDataset, ReplicationReport, ResearcherApproval)


class RobustnessThresholds(Model):
    max_std: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_range: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    min_successful_runs: int | None = Field(default=None, ge=1, le=20)


class RobustnessRequest(Model):
    study_id: str = Field(min_length=1, max_length=128, pattern=r'\S')
    experiment_id: str = Field(min_length=1, max_length=128, pattern=r'\S')
    code: str = Field(min_length=1, max_length=200_000, pattern=r'\S')
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    dataset: ReplicationDataset | None = None
    required_asset_ids: list[str] = Field(default_factory=list, max_length=100)
    seeds: list[int] = Field(min_length=2, max_length=20)
    metrics: list[str] = Field(min_length=1, max_length=20)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_duration_seconds: int = Field(default=180, ge=1, le=3600)
    approval: ResearcherApproval = Field(default_factory=ResearcherApproval)
    thresholds: dict[str, RobustnessThresholds] = Field(default_factory=dict)
    confidence_interval: bool = False
    generate_figure: bool = False
    source: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode='after')
    def valid_specification(self):
        if len(set(self.seeds)) != len(self.seeds) or any(not 0 <= seed <= 2**32 - 1 for seed in self.seeds):
            raise ValueError('Seeds must be unique integers in [0, 2**32-1]')
        if len(set(self.metrics)) != len(self.metrics) or any(not name.strip() or len(name) > 128 for name in self.metrics):
            raise ValueError('Metrics must be unique explicit nonblank names of at most 128 characters')
        if set(self.thresholds) - set(self.metrics):
            raise ValueError('Thresholds must refer to selected metrics')
        if any(rule.min_successful_runs is not None and rule.min_successful_runs > len(self.seeds)
               for rule in self.thresholds.values()):
            raise ValueError('Minimum observations cannot exceed requested seed count')
        json.dumps([self.parameters, self.source], allow_nan=False)
        return self


class SeedRun(Model):
    seed: int
    execution_id: str
    execution: ExperimentResult | None = None
    error: ExecutionError | None = None
    missing_metrics: list[str] = Field(default_factory=list)


class MetricSummary(Model):
    observation_count: int
    seeds: list[int]
    values: list[float]
    mean: float | None = None
    sample_std: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    range: float | None = None
    median: float | None = None
    standard_error: float | None = None
    confidence_interval_95: list[float] | None = None
    threshold_assessments: dict[str, bool | None] = Field(default_factory=dict)


class RobustnessReport(Model):
    request: RobustnessRequest
    specification_sha256: str
    study_id: str
    experiment_id: str
    requested_seeds: list[int]
    status: str
    completed_runs: int
    failed_runs: int
    unattempted_seeds: list[int]
    runs: list[SeedRun]
    summaries: dict[str, MetricSummary]
    artifacts: list[FigureArtifact]
    code_sha256: str
    dataset_provenance: ReplicationDataset | None
    dependency_versions: dict[str, dict[str, JsonValue]]
    warnings: list[str]
    duration_seconds: float
    report_timestamp: str


def robustness_digest(request: RobustnessRequest) -> str:
    request = RobustnessRequest.model_validate(request.model_dump())
    data = json.dumps(request.model_dump(mode='json', exclude={'approval'}), sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(b'pre-robustness-v1\n' + data).hexdigest()


def robustness_from_replication(report: ReplicationReport, *, study_id, seeds, metrics, **settings):
    """Separate, unapproved evaluation of the exact executed reconstruction."""
    if 'approval' in settings:
        raise ValueError('A derived evaluation requires fresh approval after proposal creation')
    report = ReplicationReport.model_validate(report.model_dump())
    if report.execution is None or report.execution.status != 'success' or report.specification.code is None:
        raise ValueError('A successfully executed reconstruction is required')
    if hashlib.sha256(report.specification.code.encode()).hexdigest() != report.code_sha256:
        raise ValueError('Source code does not match executed evidence')
    return RobustnessRequest(study_id=study_id, experiment_id=report.experiment_id,
        code=report.specification.code, parameters=report.execution.parameters,
        dataset=report.dataset_provenance, required_asset_ids=report.specification.required_asset_ids,
        seeds=seeds, metrics=metrics, source={'kind': 'replication', 'specification_sha256': report.specification_sha256,
            'report_timestamp': report.report_timestamp}, **settings)


def robustness_from_optimization(report: OptimizationResult, *, study_id, seeds, metrics, **settings):
    """Evaluate a measured best configuration; does not imply held-out testing."""
    if 'approval' in settings:
        raise ValueError('A derived evaluation requires fresh approval after proposal creation')
    report = OptimizationResult.model_validate(report.model_dump())
    if report.best_parameters is None or not report.successful_trial_count:
        raise ValueError('An observed successful optimized configuration is required')
    if hashlib.sha256(report.request.code.encode()).hexdigest() != report.code_sha256:
        raise ValueError('Source code does not match executed evidence')
    return RobustnessRequest(study_id=study_id, experiment_id=report.request.experiment_id,
        code=report.request.code, parameters=report.best_parameters, dataset=report.request.dataset,
        required_asset_ids=report.request.required_asset_ids, seeds=seeds, metrics=metrics,
        source={'kind': 'optimization', 'study_id': report.study_id, 'request_sha256': report.request_sha256,
                'report_timestamp': report.report_timestamp, 'independent_test_evaluation': False}, **settings)


def _summary(seeds, values, interval, thresholds):
    result = MetricSummary(observation_count=len(values), seeds=seeds, values=values)
    if values:
        array = np.array(values, dtype=float)
        with np.errstate(over='ignore', invalid='ignore'):
            statistics = dict(mean=float(np.mean(array)), minimum=float(np.min(array)),
                              maximum=float(np.max(array)), range=float(np.ptp(array)), median=float(np.median(array)))
            if len(values) >= 2:
                std = float(np.std(array, ddof=1))
                statistics.update(sample_std=std, standard_error=std / math.sqrt(len(values)))
        for key, value in statistics.items():
            setattr(result, key, value if math.isfinite(value) else None)
        if interval and result.mean is not None and result.standard_error is not None:
            margin = float(t.ppf(.975, len(values) - 1)) * result.standard_error
            bounds = [result.mean - margin, result.mean + margin]
            if all(math.isfinite(value) for value in bounds):
                result.confidence_interval_95 = bounds
    if thresholds:
        for name, observed, bound in [('max_std', result.sample_std, thresholds.max_std),
                                      ('max_range', result.range, thresholds.max_range)]:
            if bound is not None:
                result.threshold_assessments[name] = observed <= bound if observed is not None else None
        if thresholds.min_successful_runs is not None:
            result.threshold_assessments['min_successful_runs'] = len(values) >= thresholds.min_successful_runs
    return result


class RobustnessService:
    def __init__(self, experiment_service: ExperimentService, *, artifact_store: ArtifactStore | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.experiments, self.artifact_store, self.clock = experiment_service, artifact_store, clock

    def run(self, specification: RobustnessRequest | dict, *, available_dataset_ids: Collection[str] = (),
            available_asset_ids: Collection[str] = ()) -> RobustnessReport:
        request = RobustnessRequest.model_validate(specification.model_dump() if isinstance(specification, RobustnessRequest) else specification)
        start, digest = self.clock(), robustness_digest(request)
        runs, artifacts = [], []
        warnings = ['Studies execute sequentially; the executor must enforce fresh process/filesystem state and deadlines.',
                    'Requested seeds do not prove runtime application; inspect per-run seed metadata.',
                    'Runtime seeding covers Python random and NumPy legacy RNG only. Code may override seeds; other libraries and hardware may remain uncontrolled.',
                    'Observed variation and configured thresholds do not establish scientific validity.',
                    'Student t intervals assume independent observations and an approximately normal sampling distribution of the mean; seed runs on shared data may violate these assumptions.',
                    'Evaluation of an optimized configuration on selection data is not independent test evaluation.']
        approved = (request.approval.approved and request.approval.approved_by is not None
                    and request.approval.specification_sha256 == digest)
        if not approved:
            status = 'approval_required'
        elif ((request.dataset and request.dataset.dataset_id not in available_dataset_ids)
              or any(asset not in available_asset_ids for asset in request.required_asset_ids)):
            status = 'missing_inputs'
        else:
            status = 'completed'
            for seed in request.seeds:
                remaining = request.max_duration_seconds - (self.clock() - start)
                if remaining < 1:
                    status = 'budget_exhausted'
                    break
                execution_id = 'robustness-' + uuid4().hex
                run = SeedRun(seed=seed, execution_id=execution_id)
                runs.append(run)
                try:
                    run.execution = self.experiments.run(ExperimentRequest(
                        experiment_id=execution_id, code=request.code, parameters=request.parameters,
                        random_seed=seed, timeout_seconds=min(request.timeout_seconds, int(remaining)),
                        dataset_id=request.dataset.dataset_id if request.dataset else None,
                        metadata={'study_id': request.study_id, 'source_experiment_id': request.experiment_id,
                                  'specification_sha256': digest, 'fresh_state_required': True,
                                  'dataset_provenance': request.dataset.model_dump(mode='json') if request.dataset else None,
                                  'source': request.source}))
                    run.missing_metrics = [name for name in request.metrics if name not in run.execution.metrics]
                    run.error = run.execution.error
                except Exception:
                    run.error = ExecutionError(type='InvalidExecution', message='Executor failed or returned an invalid scientific record')
                    run.missing_metrics = list(request.metrics)
            if self.clock() - start >= request.max_duration_seconds:
                status = 'budget_exhausted'
        summaries = {}
        for name in request.metrics:
            observations = [(run.seed, run.execution.metrics[name]) for run in runs
                            if run.execution and run.execution.status == 'success' and name in run.execution.metrics]
            summaries[name] = _summary([seed for seed, value in observations], [value for seed, value in observations],
                                       request.confidence_interval, request.thresholds.get(name))
            if len(observations) < len(request.seeds):
                warnings.append(f'Metric {name}: {len(observations)} of {len(request.seeds)} requested observations contributed.')
            if observations and summaries[name].mean is None:
                warnings.append(f'Metric {name}: summary arithmetic overflowed; affected statistics are unavailable.')
        if request.generate_figure and any(summary.values for summary in summaries.values()):
            try:
                if self.artifact_store is None:
                    raise ValueError('Artifact store is required')
                artifacts = self._figure(request, summaries)
            except Exception:
                warnings.append('Robustness figure could not be generated; numerical and execution evidence is preserved.')
        successful = sum(run.execution is not None and run.execution.status == 'success' for run in runs)
        if status == 'completed' and (successful < len(runs) or any(run.missing_metrics for run in runs)):
            status = 'completed_with_failures'
        return RobustnessReport(request=request, specification_sha256=digest, study_id=request.study_id,
            experiment_id=request.experiment_id, requested_seeds=request.seeds, status=status,
            completed_runs=successful, failed_runs=len(runs) - successful, unattempted_seeds=request.seeds[len(runs):],
            runs=runs, summaries=summaries, artifacts=artifacts, code_sha256=hashlib.sha256(request.code.encode()).hexdigest(),
            dataset_provenance=request.dataset,
            dependency_versions={run.execution_id: run.execution.execution_metadata.get('dependencies', {})
                                 for run in runs if run.execution}, warnings=warnings,
            duration_seconds=max(0., self.clock() - start), report_timestamp=datetime.now(timezone.utc).isoformat())

    def _figure(self, request, summaries):
        # Backend-owned plotting only; uses bounded existing PNG capture. Sequential only.
        import matplotlib
        matplotlib.use('Agg', force=True)
        import matplotlib.pyplot as plt
        with matplotlib.rc_context({'text.usetex': False}):
            plt.close('all')
            try:
                figure, axes = plt.subplots(len(summaries), 1, figsize=(6, min(30, 3 * len(summaries))), squeeze=False)
                for axis, (name, summary) in zip(axes[:, 0], summaries.items()):
                    axis.scatter(summary.seeds, summary.values, label='Successful observations')
                    if summary.mean is not None:
                        axis.axhline(summary.mean, label='Observed mean', linestyle='--')
                    axis.set_xlabel('Requested random seed')
                    axis.set_ylabel(name, parse_math=False)
                    axis.legend()
                figure.tight_layout()
                artifacts, errors = capture_figures(request.study_id, self.artifact_store, FigureLimits())
                if errors:
                    raise ValueError('Figure capture failed')
                return artifacts
            finally:
                plt.close('all')
