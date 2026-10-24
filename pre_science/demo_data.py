"""Deterministic local CSV demonstration: python -m pre_science.demo_data."""

import io
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from .data import DatasetArtifactStore, DatasetService
from .schemas import DatasetProcessingRequest


DEMO_CSV = '''age,score,label
20,10,A
30,,B
30,,B
40,30,A
50,50,
,40,B
'''


def main():
    root = Path('.runtime/dataset-demo') / uuid4().hex
    inputs = root / 'inputs'
    inputs.mkdir(parents=True)
    (inputs / 'study.csv').write_bytes(DEMO_CSV.encode('utf-8'))
    store = DatasetArtifactStore(root / 'outputs')
    service = DatasetService(inputs, {'demo-study': 'study.csv'}, artifact_store=store)
    inspected = service.inspect({'dataset_id': 'demo-study'})
    result = service.process(DatasetProcessingRequest.model_validate({
        'dataset_id': 'demo-study', 'transformations': [
            {'operation': 'drop_missing', 'columns': ['label']},
            {'operation': 'drop_duplicates'},
            {'operation': 'fill_median', 'columns': ['age', 'score']},
            {'operation': 'standardize', 'columns': ['age', 'score']},
        ],
    }))
    if result.status != 'success':
        raise RuntimeError(result.model_dump_json())
    cleaned = store.retrieve(result.artifact.artifact_id)
    actual = pd.read_csv(io.BytesIO(cleaned))
    assert actual.shape == (4, 3)
    assert not actual.isna().any().any()
    assert [entry.rows_removed for entry in result.transformations] == [1, 1, 0, 0]
    print(json.dumps({'inspection': inspected.model_dump(mode='json'),
                      'processing': result.model_dump(mode='json'),
                      'retrieved_csv_bytes': len(cleaned),
                      'retrieved_csv': cleaned.decode('utf-8')}, indent=2, allow_nan=False))
    # Explicit retention for handoff/inspection. Never automatically delete output.


if __name__ == '__main__':
    main()
