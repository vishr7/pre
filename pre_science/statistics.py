"""Explicit statistical comparisons of supplied measurements; no execution or AI."""

from datetime import datetime, timezone
import json
import math
from typing import Annotated, Literal
import warnings

import numpy as np
from pydantic import Field, JsonValue, model_validator
from scipy import stats
from scipy.special import gammaln

from .robustness import RobustnessReport
from .schemas import Model

Finite = Annotated[float, Field(allow_inf_nan=False)]
Test = Literal['welch', 'paired_t', 'mann_whitney']


class StatisticalRequest(Model):
    analysis_id: str = Field(min_length=1, max_length=128, pattern=r'\S')
    method_a: str = Field(min_length=1, max_length=256, pattern=r'\S')
    method_b: str = Field(min_length=1, max_length=256, pattern=r'\S')
    observations_a: list[Finite] = Field(min_length=2, max_length=10000)
    observations_b: list[Finite] = Field(min_length=2, max_length=10000)
    test: Test
    alternative: Literal['two-sided', 'greater', 'less'] = 'two-sided'
    alpha: Finite = Field(default=.05, gt=0, lt=1)
    paired: bool = False
    units: str | None = Field(default=None, max_length=128)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    provenance: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode='after')
    def valid_design(self):
        if self.paired != (self.test == 'paired_t'):
            raise ValueError('paired must be true exactly for paired_t; other tests require independent groups')
        if self.paired and len(self.observations_a) != len(self.observations_b):
            raise ValueError('Paired observations require equal lengths and meaningful correspondence in their supplied order')
        json.dumps(self.provenance, allow_nan=False)
        return self


class DescriptiveStatistics(Model):
    count: int
    mean: Finite | None
    sample_std: Finite | None
    median: Finite | None
    minimum: Finite
    maximum: Finite
    standard_error: Finite | None


class ConfidenceInterval(Model):
    status: Literal['available', 'unavailable']
    confidence_level: Finite
    lower: Finite | None = None
    upper: Finite | None = None
    quantity: str = 'Population mean difference A minus B'
    convention: str = 'Two-sided interval at 1-alpha, including for one-sided tests'
    assumptions: list[str]
    reason: str | None = None


class EffectSize(Model):
    name: str
    value: Finite | None
    definition: str
    reason: str | None = None


class StatisticalReport(Model):
    request: StatisticalRequest
    analysis_id: str
    source_ids: list[str]
    status: Literal['available', 'unavailable']
    test_name: str
    hypothesis: str
    comparison_direction: str = 'A minus B; greater means A exceeds B'
    statistic: Finite | None
    degrees_of_freedom: Finite | None
    p_value: Finite | None
    alpha: Finite
    below_threshold: bool | None
    estimated_mean_difference: Finite | None
    confidence_interval: ConfidenceInterval
    effect_size: EffectSize
    group_a: DescriptiveStatistics
    group_b: DescriptiveStatistics
    paired_differences: DescriptiveStatistics | None
    provenance: dict[str, JsonValue]
    assumption_warnings: list[str]
    limitations: list[str]
    unavailable_reason: str | None
    summary: str
    report_timestamp: str
    dependency_versions: dict[str, str]


def _finite(value):
    return float(value) if value is not None and np.isfinite(value) else None


def _describe(values):
    with np.errstate(over='ignore', invalid='ignore'):
        std = _finite(np.std(values, ddof=1))
        return DescriptiveStatistics(count=len(values), mean=_finite(np.mean(values)), sample_std=std,
            median=_finite(np.median(values)), minimum=float(np.min(values)), maximum=float(np.max(values)),
            standard_error=_finite(std / math.sqrt(len(values))) if std is not None else None)


def analyze_statistics(specification: StatisticalRequest | dict) -> StatisticalReport:
    """Keep original observations; select no tests or preprocessing implicitly."""
    request = StatisticalRequest.model_validate(specification.model_dump() if isinstance(specification, StatisticalRequest) else specification)
    a, b = np.asarray(request.observations_a), np.asarray(request.observations_b)
    desc_a, desc_b = _describe(a), _describe(b)
    assumptions = ['Independence is a design assumption; it has not been empirically verified.',
                   'Repeated seeds and overlapping data splits are not automatically independent replications.']
    limitations = ['Statistical significance does not establish practical importance, causality, scientific validity, or successful reproduction.',
                  'A nonsignificant result does not establish equivalence; a p-value is not the probability that the null hypothesis is true.',
                  'Selection on the same evaluation data can bias subsequent comparisons, including optimized configurations.',
                  'No multiple-comparison correction or power analysis is performed.']
    ci_assumptions = ['Independent sampling units (pairs for paired tests); approximately normal sampling distribution of the mean difference.']
    ci = ConfidenceInterval(status='unavailable', confidence_level=1 - request.alpha,
                            assumptions=ci_assumptions, reason='No mean-difference interval is implemented for Mann-Whitney U')
    statistic = p_value = df = difference = None
    paired_desc = None
    reason = None
    effect_value = None
    effect_reason = 'Effect size denominator is zero or numerical arithmetic is unavailable'
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always', RuntimeWarning)
        difference = _finite(np.mean(a) - np.mean(b))
        if request.test == 'mann_whitney':
            test_name = 'Mann-Whitney U (SciPy auto method)'
            assumptions.append('Independent groups are required; U compares distributions/stochastic ordering and does not universally test equality of medians when shapes differ.')
            result = stats.mannwhitneyu(a, b, alternative=request.alternative, method='auto')
            statistic, p_value = _finite(result.statistic), _finite(result.pvalue)
            effect_value = _finite(2 * result.statistic / (len(a) * len(b)) - 1)
            effect_name, effect_definition = 'rank_biserial', '2*U_A/(n_A*n_B)-1; positive means A tends to exceed B; ties count half'
        else:
            if request.test == 'paired_t':
                test_name = 'Paired t-test'
                assumptions.append('Pairing requires meaningful correspondence, not merely equal sample sizes; pairs must be independent and differences approximately normal for exact small-sample inference.')
                differences = a - b
                if np.all(np.isfinite(differences)):
                    paired_desc = _describe(differences)
                    difference = paired_desc.mean
                    se = paired_desc.standard_error
                    df = float(len(a) - 1)
                    if paired_desc.sample_std is not None and paired_desc.sample_std > 0:
                        effect_value = _finite(difference / paired_desc.sample_std) if difference is not None else None
                else:
                    se = None
                effect_name, effect_definition = 'cohen_dz', 'Mean(A-B) / sample standard deviation(A-B), ddof=1'
                result = stats.ttest_rel(a, b, alternative=request.alternative) if se is not None and se > 0 else None
            else:
                test_name = 'Welch unequal-variance t-test'
                assumptions.append('Independent observations/groups and approximately normal mean sampling distributions are assumed; equal variances are not assumed.')
                va, vb = np.var(a, ddof=1), np.var(b, ddof=1)
                terms = va / len(a), vb / len(b)
                se = _finite(np.sqrt(sum(terms)))
                denominator = terms[0]**2 / (len(a)-1) + terms[1]**2 / (len(b)-1)
                df = _finite(sum(terms)**2 / denominator) if denominator > 0 else None
                pooled_df = len(a) + len(b) - 2
                pooled_sd = _finite(np.sqrt(((len(a)-1)*va + (len(b)-1)*vb) / pooled_df))
                correction = math.exp(gammaln(pooled_df/2) - .5*math.log(pooled_df/2) - gammaln((pooled_df-1)/2))
                if pooled_sd is not None and pooled_sd > 0 and difference is not None:
                    effect_value = _finite(correction * difference / pooled_sd)
                effect_name, effect_definition = 'hedges_g', 'J(df)*(mean_A-mean_B)/pooled sample SD; df=n_A+n_B-2; exact gamma correction J; pooled SD is a descriptive convention, not an equal-variance test assumption'
                result = stats.ttest_ind(a, b, equal_var=False, alternative=request.alternative) if se is not None and se > 0 else None
            if result is not None:
                statistic, p_value = _finite(result.statistic), _finite(result.pvalue)
            ci.reason = 'Zero standard error, undefined variance, or numerical overflow prevents a t interval'
            if se is not None and se > 0 and df is not None and df > 0 and difference is not None:
                margin = stats.t.ppf(1 - request.alpha/2, df) * se
                lower, upper = _finite(difference - margin), _finite(difference + margin)
                if lower is not None and upper is not None:
                    ci.status, ci.lower, ci.upper, ci.reason = 'available', lower, upper, None
        if caught:
            assumptions.append('SciPy/NumPy reported numerical precision warnings; interpret near-constant or extreme data cautiously.')
    if statistic is None or p_value is None:
        p_value = None
        reason = 'Test statistic or p-value is undefined for zero variation or numerical overflow; no infinite values are reported'
    if effect_value is not None:
        effect_reason = None
    below = p_value < request.alpha if p_value is not None else None
    parameter = 'distribution of A versus B' if request.test == 'mann_whitney' else 'population mean of A minus B'
    hypothesis = f'Null: no difference in {parameter}. Alternative ({request.alternative}): '
    hypothesis += {'two-sided': 'A differs from B.', 'greater': 'A exceeds B.', 'less': 'A is below B.'}[request.alternative]
    summary = (f'{test_name}: statistic={statistic:.6g}, p={p_value:.6g}; p < alpha ({request.alpha:g}): {below}. '
               'Statistical evidence does not establish practical importance.' if p_value is not None
               else f'{test_name}: unavailable. {reason}.')
    import scipy
    return StatisticalReport(request=request, analysis_id=request.analysis_id, source_ids=request.source_ids,
        status='available' if p_value is not None else 'unavailable', test_name=test_name, hypothesis=hypothesis,
        statistic=statistic, degrees_of_freedom=df, p_value=p_value, alpha=request.alpha, below_threshold=below,
        estimated_mean_difference=difference, confidence_interval=ci,
        effect_size=EffectSize(name=effect_name, value=effect_value, definition=effect_definition, reason=effect_reason),
        group_a=desc_a, group_b=desc_b, paired_differences=paired_desc, provenance=request.provenance,
        assumption_warnings=assumptions, limitations=limitations, unavailable_reason=reason,
        summary=summary, report_timestamp=datetime.now(timezone.utc).isoformat(),
        dependency_versions={'numpy': np.__version__, 'scipy': scipy.__version__})


def statistics_from_robustness(first: RobustnessReport, second: RobustnessReport, *, analysis_id: str,
        metric: str, test: Test, paired: bool = False, conditions_a: dict[int, str] | None = None,
        conditions_b: dict[int, str] | None = None, **options) -> StatisticalRequest:
    """Reject incomplete observations; require explicit condition attestation for pairs.

    Equal seeds alone do not establish correspondence. Conditions are supplied by
    the trusted caller after reviewing the experimental design, not inferred here.
    """
    if not metric.strip():
        raise ValueError('A named metric is required')
    reports = [RobustnessReport.model_validate(report.model_dump()) for report in (first, second)]
    observations, provenance = [], []
    for report in reports:
        by_seed = {}
        for run in report.runs:
            execution = run.execution
            if run.seed in by_seed or execution is None or execution.status != 'success' or metric not in execution.metrics:
                raise ValueError('All requested seed observations must be unique, successful and contain the metric; preprocess explicitly otherwise')
            if execution.random_seed != run.seed:
                raise ValueError('Recorded seed and execution seed disagree')
            by_seed[run.seed] = execution.metrics[metric]
        if set(by_seed) != set(report.requested_seeds) or len(report.requested_seeds) != len(by_seed):
            raise ValueError('Missing or ambiguous seed observations')
        observations.append(by_seed)
        provenance.append({'study_id': report.study_id, 'experiment_id': report.experiment_id,
            'specification_sha256': report.specification_sha256, 'code_sha256': report.code_sha256,
            'dataset': report.dataset_provenance.model_dump(mode='json') if report.dataset_provenance else None,
            'source': report.request.source, 'report_timestamp': report.report_timestamp,
            'execution_ids': {str(run.seed): run.execution_id for run in report.runs}})
    seeds_a, seeds_b = list(observations[0]), list(observations[1])
    if paired:
        if set(seeds_a) != set(seeds_b) or conditions_a is None or conditions_b is None:
            raise ValueError('Paired comparisons require matching seeds and explicit corresponding-condition identifiers for both methods')
        if set(conditions_a) != set(seeds_a) or set(conditions_b) != set(seeds_b):
            raise ValueError('Condition identifiers must cover exactly the observed seeds')
        if any(not isinstance(conditions_a[seed], str) or not conditions_a[seed].strip()
               or conditions_a[seed] != conditions_b[seed] for seed in seeds_a):
            raise ValueError('Paired experimental conditions do not match')
        seeds_b = seeds_a
    return StatisticalRequest(analysis_id=analysis_id, method_a=reports[0].experiment_id,
        method_b=reports[1].experiment_id, observations_a=[observations[0][seed] for seed in seeds_a],
        observations_b=[observations[1][seed] for seed in seeds_b], test=test, paired=paired,
        source_ids=[report.study_id for report in reports], provenance={'metric': metric, 'sources': provenance,
            'seeds_a': seeds_a, 'seeds_b': seeds_b,
            'pairing_conditions': {str(seed): conditions_a[seed] for seed in seeds_a} if paired else None,
            'pairing_attested_by_caller': paired, 'independence_established': False}, **options)
