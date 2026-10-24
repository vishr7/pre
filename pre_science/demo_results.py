"""Normalize genuine retained demos. Only this CLI reads/writes known demo files."""
import json
from pathlib import Path
from uuid import uuid4

from .latex_tables import LatexTableResponse
from .robustness import RobustnessReport
from .statistics import StatisticalReport
from .schemas import ScientificWorkflowReport
from .results import scientific_response


def _load_demo(folder):
    candidates = list((Path('.runtime') / folder).glob('*/report.json'))
    if not candidates:
        raise ValueError(f'No retained {folder} demo report. Run the corresponding trusted demo first.')
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return json.loads(latest.read_text(encoding='utf-8'))


def build_examples(workflow, robustness, statistics, table):
    """Consume validated actual reports; no scientific execution occurs here."""
    records = {'experiment': workflow.baseline, 'replication': workflow.replication,
        'optimization': workflow.optimization, 'robustness': robustness, 'statistics': statistics,
        'latex_table': table, 'dataset_inspection': workflow.dataset_inspection,
        'dataset_processing': workflow.dataset_processing}
    if any(record is None for record in records.values()):
        raise ValueError('The retained workflow must contain all demonstration stages')
    # This local map demonstrates reference resolution, not production auth.
    originals = {'demo-original:' + name: record.model_dump(mode='json') for name, record in records.items()}
    responses = {name: scientific_response(record, original_reference='demo-original:' + name)
                 for name, record in records.items()}
    return {'description': 'Normalization of genuine retained execution reports; no experiments rerun.',
            'reference_scope': 'Local demo lookup only; production reference resolution requires backend authorization.',
            'responses': responses, 'original_records': originals}


def main():
    workflow = ScientificWorkflowReport.model_validate(_load_demo('end-to-end')['scientific'])
    robustness = RobustnessReport.model_validate(_load_demo('robustness')['first'])
    statistics = StatisticalReport.model_validate(_load_demo('statistics'))
    table = LatexTableResponse.model_validate(_load_demo('latex-tables')['tables']['experiment'])
    payload = build_examples(workflow, robustness, statistics, table)
    root = Path('.runtime/results') / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    output = root / 'report.json'
    output.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'report_path': str(output), 'description': payload['description'],
        'examples': {name: {'summary': response['scientific']['summary'],
            'visible_actions': [action['action_id'] for action in response['scientific']['next_actions']],
            'blocked_actions': {action['action_id']: action['missing_inputs']
                for action in response['scientific']['all_next_actions'] if not action['eligible']}}
            for name, response in payload['responses'].items()}}, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
