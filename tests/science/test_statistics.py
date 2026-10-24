"""Real SciPy numerical checks; robustness fixtures mock execution, not statistics."""
import math
from unittest.mock import Mock

import numpy as np
import pytest
from pydantic import ValidationError
from scipy import stats
from scipy.special import gamma

from pre_science.experiment import ExperimentService
from pre_science.robustness import RobustnessRequest, RobustnessService, robustness_digest
from pre_science.schemas import ExecutionOutput, ResearcherApproval
from pre_science.statistics import (StatisticalRequest, StatisticalReport, analyze_statistics,
                                   statistics_from_robustness)

A = [1., 3., 5., 7., 8.]
B = [0., 2., 4., 4., 6.]


def request(**updates):
    return StatisticalRequest.model_validate(dict(analysis_id='test', method_a='A', method_b='B',
        observations_a=A, observations_b=B, test='welch') | updates)


@pytest.mark.parametrize('test', ['welch', 'paired_t', 'mann_whitney'])
@pytest.mark.parametrize('alternative', ['two-sided', 'greater', 'less'])
def test_tests_match_scipy(test, alternative):
    report = analyze_statistics(request(test=test, paired=test == 'paired_t', alternative=alternative))
    if test == 'welch':
        expected = stats.ttest_ind(A, B, equal_var=False, alternative=alternative)
    elif test == 'paired_t':
        expected = stats.ttest_rel(A, B, alternative=alternative)
    else:
        expected = stats.mannwhitneyu(A, B, alternative=alternative, method='auto')
    assert report.statistic == pytest.approx(expected.statistic)
    assert report.p_value == pytest.approx(expected.pvalue)
    assert report.estimated_mean_difference == pytest.approx(np.mean(A) - np.mean(B))
    assert report.below_threshold == (expected.pvalue < .05)


@pytest.mark.parametrize('test', ['welch', 'paired_t'])
def test_intervals_and_effects(test):
    report = analyze_statistics(request(test=test, paired=test == 'paired_t'))
    if test == 'welch':
        result = stats.ttest_ind(A, B, equal_var=False)
        df = len(A) + len(B) - 2
        correction = gamma(df/2) / (math.sqrt(df/2) * gamma((df-1)/2))
        pooled = math.sqrt(((len(A)-1)*np.var(A, ddof=1) + (len(B)-1)*np.var(B, ddof=1)) / df)
        effect = correction * (np.mean(A) - np.mean(B)) / pooled
    else:
        result = stats.ttest_rel(A, B)
        effect = np.mean(np.array(A)-B) / np.std(np.array(A)-B, ddof=1)
        assert report.paired_differences.count == 5
        assert report.paired_differences.mean == pytest.approx(np.mean(np.array(A)-B))
    interval = result.confidence_interval(confidence_level=.95)
    assert report.confidence_interval.lower == pytest.approx(interval.low)
    assert report.confidence_interval.upper == pytest.approx(interval.high)
    assert report.degrees_of_freedom == pytest.approx(result.df)
    assert report.effect_size.value == pytest.approx(effect)


def test_unequal_samples_descriptions_and_serialization():
    req = request(observations_b=[1., 2., 3.], provenance={'replication_id': 'r', 'optimization_id': 'o'})
    before = req.model_dump_json()
    report = analyze_statistics(req)
    assert report.group_a.mean == pytest.approx(np.mean(A))
    assert report.group_a.sample_std == pytest.approx(np.std(A, ddof=1))
    assert report.group_a.standard_error == pytest.approx(np.std(A, ddof=1)/math.sqrt(5))
    assert report.group_a.median == np.median(A)
    assert report.group_a.minimum == min(A) and report.group_a.maximum == max(A)
    assert report.provenance == req.provenance
    assert StatisticalReport.model_validate_json(report.model_dump_json()) == report
    assert analyze_statistics(req).summary == report.summary
    assert req.model_dump_json() == before


@pytest.mark.parametrize('changes', [{'observations_a': []}, {'observations_a': [1.]},
    {'observations_a': [float('nan'), 1.]}, {'observations_b': [float('inf'), 1.]},
    {'observations_a': [None, 1.]}, {'observations_a': [True, 1.]}, {'observations_a': ['1', 2.]},
    {'test': 'paired_t'}, {'paired': True}, {'test': 'unsupported'}, {'alpha': 0.}, {'alpha': 1.},
    {'alpha': float('nan')}, {'provenance': {'bad': float('inf')}},
    {'test': 'paired_t', 'paired': True, 'observations_b': [1., 2.]}])
def test_invalid_requests(changes):
    with pytest.raises(ValidationError):
        request(**changes)


@pytest.mark.parametrize('test', ['welch', 'paired_t'])
@pytest.mark.parametrize('b', [[1., 1., 1.], [2., 2., 2.]])
def test_degenerate_variances_are_explicitly_unavailable(test, b):
    report = analyze_statistics(request(test=test, paired=test == 'paired_t', observations_a=[1., 1., 1.], observations_b=b))
    assert report.status == 'unavailable' and report.p_value is report.statistic is None
    assert report.confidence_interval.status == 'unavailable'
    assert report.effect_size.value is None and report.effect_size.reason
    assert report.unavailable_reason
    assert 'NaN' not in report.model_dump_json() and 'Infinity' not in report.model_dump_json()


def test_constant_one_group_and_mann_whitney_ties():
    assert analyze_statistics(request(observations_a=[1., 1., 1.])).status == 'available'
    report = analyze_statistics(request(test='mann_whitney', observations_a=[1., 1.], observations_b=[1., 1.]))
    expected = stats.mannwhitneyu([1., 1.], [1., 1.], method='auto')
    if np.isfinite(expected.pvalue):
        assert report.p_value == expected.pvalue
    else:
        assert report.status == 'unavailable' and report.p_value is None
    assert report.statistic == expected.statistic and report.effect_size.value == 0.
    assert report.confidence_interval.status == 'unavailable'


def test_effect_orientation_and_strict_threshold():
    report = analyze_statistics(request(test='mann_whitney'))
    assert report.effect_size.value == pytest.approx(2*report.statistic/(len(A)*len(B))-1)
    p = analyze_statistics(request()).p_value
    assert analyze_statistics(request(alpha=p)).below_threshold is False
    assert analyze_statistics(request(alpha=float(np.nextafter(p, 1.)))).below_threshold is True
    reverse = analyze_statistics(request(observations_a=B, observations_b=A))
    assert reverse.effect_size.value < 0


def test_extreme_finite_values_stay_json_safe():
    report = analyze_statistics(request(observations_a=[1e308, -1e308], observations_b=[0., 1.]))
    assert report.status == 'unavailable'
    assert 'Infinity' not in report.model_dump_json()


def robustness(name, seeds):
    req = RobustnessRequest(study_id=name, experiment_id=name, code='pass', seeds=seeds, metrics=['score'])
    req.approval = ResearcherApproval(approved=True, approved_by='fixture', specification_sha256=robustness_digest(req))
    executor = Mock()
    executor.execute.side_effect = lambda req: ExecutionOutput(status='success', exit_code=0,
        metrics={'score': req.random_seed / 10 + (0.01 * req.random_seed**2 if name == 'B' else 0.)})
    return RobustnessService(ExperimentService(executor)).run(req)


def test_robustness_pair_alignment_and_source_preservation():
    a, b = robustness('A', [1, 2, 3]), robustness('B', [3, 1, 2])
    snapshot = b.model_dump_json()
    conditions = {1: 'split-1', 2: 'split-2', 3: 'split-3'}
    req = statistics_from_robustness(a, b, analysis_id='paired', metric='score', test='paired_t',
        paired=True, conditions_a=conditions, conditions_b=conditions)
    assert req.observations_b == pytest.approx([.11, .24, .39])
    assert req.provenance['seeds_b'] == [1, 2, 3]
    assert req.source_ids == ['A', 'B']
    assert req.provenance['sources'][1]['code_sha256'] == b.code_sha256
    assert b.model_dump_json() == snapshot
    assert analyze_statistics(req).status == 'available'


@pytest.mark.parametrize('failure', ['conditions', 'different_conditions', 'seeds', 'metric', 'duplicate', 'missing', 'failed'])
def test_ambiguous_pairing_and_missing_observations_rejected(failure):
    a, b = robustness('A', [1, 2, 3]), robustness('B', [1, 2, 3])
    ca = {1: 's1', 2: 's2', 3: 's3'}
    cb = ca.copy()
    if failure == 'different_conditions':
        cb[2] = 'wrong'
    if failure == 'seeds':
        b = robustness('B', [1, 2, 4])
    if failure == 'metric':
        del b.runs[0].execution.metrics['score']
    if failure == 'duplicate':
        b.runs.append(b.runs[0])
    if failure == 'missing':
        b.runs.pop()
    if failure == 'failed':
        b.runs[0].execution = None
    with pytest.raises(ValueError):
        statistics_from_robustness(a, b, analysis_id='bad', metric='score', test='paired_t', paired=True,
                                  conditions_a=ca, conditions_b=None if failure == 'conditions' else cb)
