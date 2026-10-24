"""Trusted Iris split/model-seed sensitivity, not independent test validation."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .experiment import ExperimentService
from .integration import read_verified_artifact
from .plots import ArtifactStore
from .robustness import RobustnessRequest, RobustnessService, robustness_digest
from .schemas import ResearcherApproval
from .trusted_demo import TrustedDemoExecutor

CODE = '''
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score
assert 'previous_run' not in globals()
previous_run = True
x, y = load_iris(return_X_y=True)
x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.3,
    random_state=random_seed, stratify=y)
model = DecisionTreeClassifier(max_depth=parameters['max_depth'], random_state=random_seed)
model.fit(x_train, y_train)
report_metric('accuracy', float(accuracy_score(y_test, model.predict(x_test))))
'''


def run_demo(root: Path):
    root = Path(root)
    store = ArtifactStore(root / 'figures')
    service = RobustnessService(ExperimentService(TrustedDemoExecutor(
        {hashlib.sha256(CODE.encode()).hexdigest()}, work_root=root / 'workers', artifact_root=root / 'run-figures')),
        artifact_store=store)
    request = RobustnessRequest(study_id='local-iris-seeds', experiment_id='local-iris-tree', code=CODE,
        parameters={'max_depth': 3}, seeds=[1, 7, 21, 42, 123], metrics=['accuracy'],
        confidence_interval=True, generate_figure=True, max_duration_seconds=180,
        source={'dataset': 'sklearn bundled Iris', 'interpretation': 'Sensitivity to partitioning and model randomness; shared observations across splits.'})
    request.approval = ResearcherApproval(approved=True, approved_by='trusted-local-demo',
        specification_sha256=robustness_digest(request))
    first, repeated = service.run(request), service.run(request)
    values = lambda report: [run.execution.metrics.get('accuracy') if run.execution else None for run in report.runs]
    reproducible = (first.completed_runs == repeated.completed_runs == 5 and
                    first.status == repeated.status == 'completed' and values(first) == values(repeated))
    for artifact in first.artifacts + repeated.artifacts:
        read_verified_artifact(store, artifact)
    payload = {'description': 'Local Iris partition/model-seed sensitivity; not independent test evaluation',
               'first': first.model_dump(mode='json'), 'repeated': repeated.model_dump(mode='json'),
               'sequence_reproduced': reproducible}
    (root / 'report.json').write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    if not reproducible or not first.artifacts or not repeated.artifacts:
        raise RuntimeError('Trusted robustness demo failed; preserved reports contain details')
    return payload


def main():
    root = Path('.runtime/robustness') / uuid4().hex
    payload = run_demo(root)
    print(json.dumps({'report_path': str(root / 'report.json'), 'sequence_reproduced': payload['sequence_reproduced'],
        'summary': payload['first']['summaries'], 'figures': payload['first']['artifacts']}, indent=2))


if __name__ == '__main__':
    main()
