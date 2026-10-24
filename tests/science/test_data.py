"""Dataset tests operate exclusively on explicit temporary CSV fixtures."""

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from pre_science.data import DatasetArtifactStore, DatasetError, DatasetLimits, DatasetService
from pre_science.demo_data import DEMO_CSV
from pre_science.experiment import ExperimentService
from pre_science.schemas import DatasetProcessingRequest, DatasetProcessingResult, DatasetSummary, ExperimentRequest, TransformationOperation
from pre_science.worker import run_worker


@pytest.fixture
def setup(tmp_path):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    store = DatasetArtifactStore(tmp_path / 'outputs')

    def make(text=DEMO_CSV, **kwargs):
        (inputs / 'study.csv').write_bytes(text.encode() if isinstance(text, str) else text)
        return DatasetService(inputs, {'study': 'study.csv'}, artifact_store=store, **kwargs)

    return make, store, inputs


def process(service, *operations):
    return service.process({'dataset_id': 'study', 'transformations': list(operations)})


def csv_frame(store, result):
    assert result.status == 'success', result.error
    return pd.read_csv(io.BytesIO(store.retrieve(result.artifact.artifact_id)))


def test_inspection_statistics_missing_duplicates_and_json(setup):
    make, _, _ = setup
    summary = make().inspect({'dataset_id': 'study'})
    assert (summary.row_count, summary.column_count, summary.duplicate_rows) == (6, 3, 1)
    columns = {column.name: column for column in summary.columns}
    assert [columns[name].missing_count for name in ('age', 'score', 'label')] == [1, 2, 1]
    assert summary.numeric_columns == ['age', 'score']
    assert summary.categorical_columns == summary.non_numeric_columns == ['label']
    assert columns['age'].statistics['mean'] == 34.0
    assert columns['age'].statistics['std'] == pytest.approx(np.std([20, 30, 30, 40, 50]))
    assert columns['score'].statistics['median'] == 35.0
    assert columns['score'].statistics['count'] == 4.0
    assert DatasetSummary.model_validate_json(summary.model_dump_json()) == summary
    json.dumps(summary.model_dump(), allow_nan=False)


def test_complete_demo_pipeline_logs_hashes_and_retrieval(setup):
    make, store, _ = setup
    result = process(make(),
                     {'operation': 'drop_missing', 'columns': ['label']},
                     {'operation': 'drop_duplicates'},
                     {'operation': 'fill_median', 'columns': ['age', 'score']},
                     {'operation': 'standardize', 'columns': ['age', 'score']})
    frame = csv_frame(store, result)
    assert frame.shape == (4, 3)
    assert frame.label.tolist() == ['A', 'B', 'A', 'B']
    np.testing.assert_allclose(frame[['age', 'score']].mean(), 0, atol=1e-15)
    np.testing.assert_allclose(frame[['age', 'score']].std(ddof=0), 1)
    assert [entry.rows_before for entry in result.transformations] == [6, 5, 4, 4]
    assert [entry.rows_after for entry in result.transformations] == [5, 4, 4, 4]
    assert [entry.rows_removed for entry in result.transformations] == [1, 1, 0, 0]
    impute, standardize = result.transformations[2:]
    assert impute.affected_values == 2
    assert impute.computed_values == {'age': {'fill_value': 30.0, 'filled_count': 1},
                                      'score': {'fill_value': 30.0, 'filled_count': 1}}
    assert standardize.computed_values['age']['mean'] == 30.0
    assert standardize.computed_values['age']['std'] == pytest.approx(np.sqrt(50))
    assert standardize.computed_values['score']['mean'] == 27.5
    assert standardize.computed_values['score']['std'] == pytest.approx(np.sqrt(118.75))
    assert standardize.parameters == {'ddof': 0}
    assert result.provenance.source_sha256 == hashlib.sha256(DEMO_CSV.encode()).hexdigest()
    output = store.retrieve(result.artifact.artifact_id)
    assert result.artifact.sha256 == result.provenance.processed_sha256 == hashlib.sha256(output).hexdigest()
    assert result.artifact.size_bytes == len(output)
    assert result.artifact.dataset_id == result.provenance.dataset_id == 'study'
    assert result.provenance.original_rows == 6 and result.provenance.final_rows == 4
    assert result.provenance.dependencies == {'pandas': pd.__version__, 'numpy': np.__version__}
    assert result.provenance.processing_timestamp.endswith('+00:00')
    assert DatasetProcessingResult.model_validate_json(result.model_dump_json()) == result
    json.dumps(result.model_dump(), allow_nan=False)


@pytest.mark.parametrize(('operation', 'expected'), [('fill_mean', 3.0), ('fill_median', 2.0)])
def test_imputation_and_counts(setup, operation, expected):
    make, store, _ = setup
    result = process(make('x,label\n1,A\n2,B\n6,C\n,D\n'),
                     {'operation': operation, 'columns': ['x']})
    assert csv_frame(store, result).x.iloc[-1] == expected
    assert result.transformations[0].computed_values['x'] == {'fill_value': expected, 'filled_count': 1}
    assert result.transformations[0].affected_values == 1


def test_minmax_and_column_operations(setup):
    make, store, _ = setup
    result = process(make('x,y,label\n2,10,A\n4,30,B\n6,50,C\n'),
                     {'operation': 'select_columns', 'columns': ['label', 'x', 'y']},
                     {'operation': 'drop_columns', 'columns': ['y']},
                     {'operation': 'minmax', 'columns': ['x']})
    frame = csv_frame(store, result)
    assert list(frame) == ['label', 'x']
    assert frame.x.tolist() == [0, .5, 1]
    assert result.transformations[-1].computed_values['x'] == {'min': 2.0, 'max': 6.0, 'range': 4.0}
    assert result.transformations[0].columns_after == ['label', 'x', 'y']
    assert result.transformations[1].columns_before == ['label', 'x', 'y']


def test_explicit_duplicate_subset(setup):
    make, store, _ = setup
    result = process(make('x,label\n1,A\n1,B\n2,C\n'),
                     {'operation': 'drop_duplicates', 'columns': ['x']})
    assert csv_frame(store, result).label.tolist() == ['A', 'C']
    assert result.transformations[0].parameters == {'keep': 'first'}
    assert result.transformations[0].rows_removed == 1


@pytest.mark.parametrize('operation', ['fill_mean', 'fill_median', 'standardize', 'minmax'])
def test_non_numeric_rejected_without_partial_export(setup, operation):
    make, store, _ = setup
    result = process(make(), {'operation': operation, 'columns': ['label']})
    assert result.status == result.transformations[0].status == 'error'
    assert 'numeric' in result.error.message
    assert result.artifact is None and not list(store.root.iterdir())


def test_invalid_column_stops_in_order_and_does_not_export(setup):
    make, store, _ = setup
    result = process(make(), {'operation': 'drop_missing', 'columns': ['label']},
                     {'operation': 'drop_columns', 'columns': ['absent']},
                     {'operation': 'drop_duplicates'})
    assert [entry.status for entry in result.transformations] == ['success', 'error']
    assert result.provenance.final_rows == 5
    assert result.transformations[1].rows_before == result.transformations[1].rows_after == 5
    assert result.final_summary is None and result.provenance.processed_sha256 is None
    assert not list(store.root.iterdir())


@pytest.mark.parametrize(('text', 'operation'), [
    ('x\n2\n2\n', 'standardize'), ('x\n2\n2\n', 'minmax'),
    ('x,label\n,A\n,B\n', 'fill_mean'), ('x,label\n,A\n,B\n', 'fill_median'),
    ('x\n', 'standardize'), ('x\n1\n', 'standardize'),
])
def test_constant_all_missing_and_insufficient_values(setup, text, operation):
    make, _, _ = setup
    options = {'ddof': 1} if text == 'x\n1\n' else {}
    result = process(make(text), {'operation': operation, 'columns': ['x'], **options})
    assert result.status == 'error' and result.artifact is None


def test_zero_rows_and_empty_after_cleaning(setup):
    make, store, _ = setup
    empty = make('x,label\n').inspect({'dataset_id': 'study'})
    assert empty.row_count == 0 and empty.warnings
    result = process(make('x,label\n1,\n2,\n'), {'operation': 'drop_missing', 'columns': ['label']})
    assert csv_frame(store, result).shape == (0, 2)
    assert result.transformations[0].rows_removed == 2
    assert result.final_summary.warnings and result.transformations[0].warnings


def test_all_missing_summary_uses_null_statistics(setup):
    make, _, _ = setup
    summary = make('x,label\n,A\n,B\n').inspect({'dataset_id': 'study'})
    assert summary.columns[0].statistics['mean'] is None
    assert summary.columns[0].missing_count == 2
    json.dumps(summary.model_dump(), allow_nan=False)


@pytest.mark.parametrize('content', [b'', b'\xff\xfe', 'x,x\n1,2\n', 'x,\n1,2\n',
                                   'x,y\n1,2,3\n', 'x,y\n1\n', 'x\n"unclosed\n',
                                   'x\n\x00\n', 'x\ninf\n', 'x\n-Infinity\n'])
def test_invalid_csv_and_nonfinite_values(setup, content):
    make, _, _ = setup
    with pytest.raises(DatasetError):
        make(content).inspect({'dataset_id': 'study'})


@pytest.mark.parametrize('limits', [DatasetLimits(max_file_bytes=10), DatasetLimits(max_rows=2),
                                    DatasetLimits(max_columns=1), DatasetLimits(max_cells=3),
                                    DatasetLimits(max_memory_bytes=1)])
def test_input_limits(setup, limits):
    make, _, _ = setup
    with pytest.raises(DatasetError):
        make(limits=limits).inspect({'dataset_id': 'study'})


def test_output_size_limit_is_structured(setup):
    make, store, _ = setup
    result = process(make(limits=DatasetLimits(max_output_bytes=1)))
    assert result.status == 'error' and result.artifact is None
    assert not list(store.root.iterdir())


@pytest.mark.parametrize('reference', ['../outside.csv', '/tmp/outside.csv', 'C:/outside.csv',
                                       'nested\\outside.csv', '.env', 'a/../outside.csv', 'a//x.csv'])
def test_unsafe_authorized_file_references_are_still_rejected(setup, reference):
    _, store, inputs = setup
    service = DatasetService(inputs, {'study': reference}, artifact_store=store)
    with pytest.raises(DatasetError):
        service.inspect({'dataset_id': 'study'})


def test_missing_and_unauthorized_files(setup):
    make, _, inputs = setup
    service = make()
    with pytest.raises(DatasetError, match='not authorized'):
        service.inspect({'dataset_id': 'unknown'})
    (inputs / 'study.csv').unlink()
    with pytest.raises(DatasetError, match='missing or unavailable'):
        service.inspect({'dataset_id': 'study'})


@pytest.mark.parametrize('identifier', ['../file.csv', '/tmp/file.csv', '', 'a' * 64])
def test_unsafe_artifact_references(setup, identifier):
    _, store, _ = setup
    with pytest.raises(DatasetError):
        store.retrieve(identifier)
    with pytest.raises(DatasetError):
        store.cleanup(identifier)


def test_artifact_cleanup_and_reproducible_bytes(setup):
    make, store, _ = setup
    service = make()
    first, second = process(service), process(service)
    assert first.artifact.artifact_id != second.artifact.artifact_id
    assert first.artifact.sha256 == second.artifact.sha256
    assert first.provenance.transformation_sha256 == second.provenance.transformation_sha256
    store.cleanup(first.artifact.artifact_id)
    with pytest.raises(DatasetError):
        store.retrieve(first.artifact.artifact_id)
    assert store.retrieve(second.artifact.artifact_id)
    store.cleanup(first.artifact.artifact_id)
    store.cleanup(second.artifact.artifact_id)
    assert not list(store.root.iterdir())


def test_hardlinks_are_rejected(setup, tmp_path):
    make, _, inputs = setup
    service = make()
    (tmp_path / 'linked.csv').hardlink_to(inputs / 'study.csv')
    with pytest.raises(DatasetError, match='links'):
        service.inspect({'dataset_id': 'study'})


def test_no_implicit_cleaning_and_reject_drop_all_columns(setup):
    make, store, _ = setup
    result = process(make())
    assert result.final_summary.row_count == 6
    assert result.final_summary.duplicate_rows == 1
    assert result.transformations == []
    result = process(make(), {'operation': 'drop_columns', 'columns': ['age', 'score', 'label']})
    assert result.status == 'error' and result.artifact is None


@pytest.mark.parametrize('operation', [
    {'operation': 'standardize', 'columns': ['x'], 'ddof': 2},
    {'operation': 'fill_mean', 'columns': ['x'], 'ddof': 0},
    {'operation': 'drop_columns'}, {'operation': 'select_columns', 'columns': ['x', 'x']},
    {'operation': 'eval', 'columns': ['x']},
])
def test_invalid_operation_models(operation):
    with pytest.raises(ValidationError):
        TransformationOperation.model_validate(operation)


def test_processed_reference_in_existing_experiment_metadata(setup, tmp_path):
    make, store, _ = setup
    result = process(make(), {'operation': 'drop_missing', 'columns': ['label']})
    reference = result.artifact.to_reference()
    # Simulate Person 4 verifying and materializing one approved input file.
    data = store.retrieve(reference.artifact_reference)
    assert hashlib.sha256(data).hexdigest() == reference.sha256
    mounted = tmp_path / 'approved.csv'
    mounted.write_bytes(data)

    class TrustedTestExecutor:
        def execute(self, request):
            return run_worker(request)

    executed = ExperimentService(TrustedTestExecutor()).run(ExperimentRequest(
        experiment_id='dataset-integration', dataset_id=reference.dataset_id,
        parameters={'dataset_path': str(mounted)},
        metadata={'processed_dataset': reference.model_dump(mode='json')},
        code='import pandas as pd\nreport_metric("rows", len(pd.read_csv(parameters["dataset_path"])))',
    ))
    assert executed.status == 'success'
    assert executed.metrics == {'rows': 5.0}
    assert executed.execution_metadata['request_metadata']['processed_dataset']['sha256'] == reference.sha256


def test_validated_request_models_and_json_roundtrip(setup):
    make, _, _ = setup
    request = DatasetProcessingRequest.model_validate({
        'dataset_id': 'study', 'transformations': [
            {'operation': 'drop_missing', 'columns': ['label']},
            {'operation': 'fill_mean', 'columns': ['age']},
            {'operation': 'standardize', 'columns': ['age']},
        ],
    })
    roundtrip = DatasetProcessingRequest.model_validate_json(request.model_dump_json())
    assert roundtrip == request
    result = make().process(roundtrip)
    assert result.status == 'success'
    assert result.transformations[-1].parameters == {'ddof': 0}
