"""Real trusted statistics -> LaTeX; references are measured local baselines."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .demo_replicate import baseline_specification
from .experiment import ExperimentService
from .latex_tables import generate_latex_table
from .replicate import ReplicationService, specification_digest
from .schemas import ExperimentRequest, ResearcherApproval
from .trusted_demo import TrustedDemoExecutor

CODE = '''
import numpy as np
values = np.array(parameters["values"], dtype=float)
report_metric("mean", float(np.mean(values)))
report_metric("std", float(np.std(values, ddof=parameters["ddof"])))
'''


def run_demo(root: Path):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    service = ExperimentService(TrustedDemoExecutor(
        {hashlib.sha256(CODE.encode()).hexdigest()}, work_root=root / 'workers', artifact_root=root / 'figures'))
    baseline = service.run(ExperimentRequest(experiment_id='local-statistics', code=CODE,
        parameters={'values': [10, 20, 30, 40, 50], 'ddof': 0}, random_seed=42))
    variant = service.run(ExperimentRequest(experiment_id='local-variant', code=CODE,
        parameters={'values': [12, 22, 32, 42, 52], 'ddof': 0}, random_seed=42))
    if baseline.status != 'success' or variant.status != 'success':
        raise RuntimeError('Trusted statistics execution did not succeed')
    specification = baseline_specification()
    specification.code = CODE
    specification.published_metrics = [item.model_copy(update={'value': baseline.metrics[item.name]})
                                       for item in specification.published_metrics]
    specification.approval = ResearcherApproval(approved=True, approved_by='trusted-local-demo',
        specification_sha256=specification_digest(specification))
    replication = ReplicationService(service).run(specification)
    if replication.all_published_metrics_agree is not True:
        raise RuntimeError('Measured local baseline comparison did not agree')
    records = {'baseline': baseline, 'variant': variant, 'replication': replication}
    tables = {}
    for kind, ids in [('experiment', ['baseline']), ('comparison', ['baseline', 'variant']),
                      ('replication', ['replication'])]:
        table = generate_latex_table({'table_type': kind, 'source_ids': ids,
            'selected_metrics': ['mean', 'std'], 'caption': 'Measured local statistics: ' + kind,
            'label': 'tab:local-' + kind}, records)
        tables[kind] = table.model_dump(mode='json')
        (root / (kind + '.tex')).write_text(table.latex_source, encoding='utf-8')
    for record in (baseline, variant):
        for value in record.metrics.values():
            assert format(value, '.4f') in tables['comparison']['latex_source']
    for value in replication.reproduced_metrics.values():
        assert format(value, '.4f') in tables['replication']['latex_source']
    payload = {'description': 'Measured local baseline, not a published finding',
               'records': {key: record.model_dump(mode='json') for key, record in records.items()},
               'tables': tables, 'presentation_values_verified': True}
    (root / 'report.json').write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    return payload


def main():
    root = Path('.runtime/latex-tables') / uuid4().hex
    payload = run_demo(root)
    print(json.dumps({'report_path': str(root / 'report.json'),
        'actual_metrics': {key: payload['records'][key]['metrics'] for key in ('baseline', 'variant')},
        'presentation_values_verified': payload['presentation_values_verified'], 'compiled': False}, indent=2))
    print(payload['tables']['experiment']['latex_source'])


if __name__ == '__main__':
    main()
