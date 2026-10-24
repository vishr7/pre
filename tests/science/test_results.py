"""Actual schema adapters; mocked executions are explicitly unit-test evidence."""
import json
from unittest.mock import Mock

import pytest

from pre_science.data import DatasetService
from pre_science.demo_iterate import iris_request
from pre_science.demo_replicate import baseline_specification
from pre_science.experiment import ExperimentService
from pre_science.integration import tool_response
from pre_science.iterate import IterationService, optimization_digest
from pre_science.latex_tables import generate_latex_table
from pre_science.replicate import ReplicationService, specification_digest
from pre_science.robustness import RobustnessRequest, RobustnessService, robustness_digest
from pre_science.statistics import StatisticalRequest, analyze_statistics
from pre_science.schemas import (Artifact, ExecutionError, ExecutionOutput, ExperimentResult,
                                FigureArtifact, ResearcherApproval, ScientificWorkflowReport)
from pre_science.results import SourceVersion, UnifiedScientificResult, normalize_scientific_result, scientific_response


def experiment(**updates):
    return ExperimentResult.model_validate(dict(experiment_id='measured', status='success', exit_code=0,
        metrics={'score': 1/3, 'zero': 0.}, parameters={}, random_seed=42,
        execution_metadata={'code_sha256': 'a'*64}) | updates)


@pytest.fixture
def reports(tmp_path):
    dataset = tmp_path / 'data'
    dataset.mkdir()
    (dataset / 'input.csv').write_text('x,y\n1,0\n1,0\n,1\n3,1\n', encoding='utf-8')
    from pre_science.data import DatasetArtifactStore
    service = DatasetService(dataset, {'input': 'input.csv'}, artifact_store=DatasetArtifactStore(tmp_path / 'artifacts'))
    inspection = service.inspect({'dataset_id': 'input'})
    processing = service.process({'dataset_id': 'input', 'transformations': [{'operation': 'drop_duplicates'}]})
    execution = Mock()
    execution.execute.return_value = ExecutionOutput(status='success', exit_code=0,
        metrics={'mean': 30., 'std': 14.142135623730951, 'accuracy': .9})
    experiments = ExperimentService(execution)
    spec = baseline_specification()
    spec.approval = ResearcherApproval(approved=True, approved_by='unit-fixture', specification_sha256=specification_digest(spec))
    replication = ReplicationService(experiments).run(spec)
    request = iris_request()
    request.n_trials = 2
    request.approval = ResearcherApproval(approved=True, approved_by='unit-fixture', specification_sha256=optimization_digest(request))
    optimization = IterationService(experiments).run(request)
    robust_request = RobustnessRequest(study_id='seeds-a', experiment_id='method-a', code='pass', seeds=[1, 2, 3], metrics=['score'])
    robust_request.approval = ResearcherApproval(approved=True, approved_by='unit-fixture', specification_sha256=robustness_digest(robust_request))
    execution.execute.side_effect = lambda req: ExecutionOutput(status='success', exit_code=0, metrics={'score': req.random_seed / 10})
    robustness = RobustnessService(experiments).run(robust_request)
    statistics = analyze_statistics(StatisticalRequest(analysis_id='comparison', method_a='a', method_b='b',
        observations_a=[1., 2., 4.], observations_b=[0., 2., 3.], test='welch'))
    table = generate_latex_table({'table_type': 'experiment', 'source_ids': ['e']}, {'e': experiment()})
    workflow = ScientificWorkflowReport(status='completed', stage='completed', summary='Unit fixture workflow',
        baseline=experiment(), replication=replication, optimization=optimization,
        dataset_inspection=inspection, dataset_processing=processing)
    return {'experiment': experiment(), 'replication': replication, 'optimization': optimization,
            'robustness': robustness, 'statistics': statistics, 'latex_table': table,
            'dataset_inspection': inspection, 'dataset_processing': processing, 'workflow': workflow}


@pytest.mark.parametrize('kind', ['experiment', 'replication', 'optimization', 'robustness', 'statistics',
                                  'latex_table', 'dataset_inspection', 'dataset_processing', 'workflow'])
def test_known_types_precision_original_payload_and_json(reports, kind):
    record = reports[kind]
    before = record.model_dump(mode='json')
    normalized = normalize_scientific_result(record)
    assert normalized.result_type == kind
    assert normalized.original_payload == before
    assert UnifiedScientificResult.model_validate_json(normalized.model_dump_json()) == normalized
    assert record.model_dump(mode='json') == before
    assert normalize_scientific_result(record).summary == normalized.summary
    if kind == 'experiment':
        assert normalized.metrics[0].value == 1/3
        assert normalized.metrics[1].value == 0.
        assert normalized.created_at is normalized.result_id is None


def test_legacy_contract_is_unchanged_and_new_types_are_supported(reports):
    response = tool_response(reports['experiment'])
    assert response['result'] == 'Execution: **success**.\n\nFigures/artifacts: 0.\n\n- score: 0.3333333333333333\n\n- zero: 0.0'
    for record in reports.values():
        assert tool_response(record)['scientific'] == record.model_dump(mode='json')
    unified = scientific_response(reports['experiment'])
    assert isinstance(unified['result'], str)
    assert unified['scientific']['original_payload'] == response['scientific']


def test_failed_and_missing_metrics_preserve_evidence():
    record = experiment(status='timeout', exit_code=124, metrics={}, error=ExecutionError(type='Timeout', message='deadline'))
    normalized = normalize_scientific_result(record)
    assert normalized.status == 'timeout' and not normalized.metrics
    assert 'Timeout: deadline' in normalized.warnings
    assert normalized.evidence.completeness == 'incomplete'


@pytest.mark.parametrize('local_path', ['C:\\private\\study.csv', '/private/results/plot.png', '/root.csv', '\\\\server\\share\\file.csv'])
def test_local_paths_require_authorized_reference_and_never_become_urls(local_path):
    record = experiment(parameters={'dataset_path': local_path},
        artifacts=[Artifact(name='old', media_type='image/png', path='/private/results/plot.png')])
    with pytest.raises(ValueError, match='original_reference'):
        normalize_scientific_result(record)
    normalized = normalize_scientific_result(record, original_reference='stored-record:123')
    encoded = normalized.model_dump_json()
    assert 'C:' not in encoded and '/private/' not in encoded
    assert local_path not in json.dumps(normalized.model_dump(mode='json'), ensure_ascii=False)
    assert normalized.original_payload is None and normalized.original_reference == 'stored-record:123'
    assert not normalized.artifacts
    with pytest.raises(ValueError, match='opaque'):
        normalize_scientific_result(experiment(), original_reference='https://server/record')


def test_opaque_figures_and_provenance_are_preserved():
    artifact = FigureArtifact(artifact_id='a'*32+'-'+'b'*32, artifact_reference='a'*32+'-'+'b'*32,
        experiment_id='measured', filename='b'*32+'.png', mime_type='image/png', size_bytes=100,
        width=1, height=1, sha256='c'*64)
    normalized = normalize_scientific_result(experiment(artifacts=[artifact]))
    assert normalized.artifacts[0].artifact_reference == artifact.artifact_reference
    assert normalized.artifacts[0].sha256 == artifact.sha256
    assert normalized.provenance['code_sha256'] == 'a'*64


def test_source_freshness_requires_both_matching_kinds():
    assert normalize_scientific_result(experiment()).freshness == 'unknown'
    assert normalize_scientific_result(experiment(), current_source_version=SourceVersion(kind='code_sha256', value='a'*64)).freshness == 'matching'
    assert normalize_scientific_result(experiment(), current_source_version=SourceVersion(kind='code_sha256', value='b'*64)).freshness == 'stale'
    assert normalize_scientific_result(experiment(), current_source_version=SourceVersion(kind='dataset_sha256', value='a'*64)).freshness == 'unknown'


def test_unknown_and_nonfinite_records_rejected():
    with pytest.raises(TypeError, match='Unsupported'):
        normalize_scientific_result({'metrics': {'score': 1.}})
    record = experiment()
    record.metrics['score'] = float('nan')
    with pytest.raises(ValueError):
        normalize_scientific_result(record)


def test_warnings_and_limitations_are_not_discarded(reports):
    record = reports['statistics']
    normalized = normalize_scientific_result(record)
    assert normalized.warnings == record.assumption_warnings
    assert normalized.limitations == record.limitations
    for kind in ('robustness', 'optimization', 'replication'):
        assert all(warning in normalize_scientific_result(reports[kind]).warnings for warning in reports[kind].warnings)


def test_demo_builds_all_types_from_validated_records(reports):
    from pre_science.demo_results import build_examples
    payload = build_examples(reports['workflow'], reports['robustness'], reports['statistics'], reports['latex_table'])
    assert len(payload['responses']) == 8
    assert len(payload['original_records']) == 8
    json.dumps(payload, allow_nan=False)
