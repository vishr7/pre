"""One trusted local scientific workflow. No AI calls, public routes, or sandbox claims."""

import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4

from .data import DatasetArtifactStore, DatasetService
from .experiment import ExperimentService
from .integration import artifact_verification, compare_optimization_runs, read_verified_artifact, tool_response
from .iterate import IterationService, optimization_digest, optimization_from_replication
from .plots import ArtifactStore
from .replicate import ReplicationService, specification_digest
from .schemas import (
    ExecutionError, ExperimentRequest, ReplicationDataset, ReplicationSpecification,
    ResearcherApproval, ScientificWorkflowReport,
)
from .trusted_demo import TrustedDemoExecutor


EXPERIMENT_CODE = '''
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score
assert "previous_experiment" not in globals()
previous_experiment = True
data = pd.read_csv(parameters["dataset_path"])
x = data[["feature"]]
y = data["label"].astype(int)
x_train, x_validation, y_train, y_validation = train_test_split(
    x, y, test_size=parameters["validation_fraction"], random_state=random_seed, stratify=y)
model = DecisionTreeClassifier(max_depth=parameters["max_depth"],
    min_samples_split=parameters["min_samples_split"], random_state=random_seed)
model.fit(x_train, y_train)
predicted = model.predict(x_validation)
report_metric("accuracy", float(accuracy_score(y_validation, predicted)))
report_metric("validation_rows", int(len(y_validation)))
print("Local validation accuracy:", accuracy_score(y_validation, predicted))
plt.figure(figsize=(4, 3))
plt.scatter(x_validation["feature"], y_validation, label="Observed")
plt.scatter(x_validation["feature"], predicted, marker="x", label="Predicted")
plt.xlabel("Feature")
plt.ylabel("Class")
plt.title("Local validation predictions")
plt.legend()
'''


def run_demo(root: Path, *, n_trials: int = 3) -> ScientificWorkflowReport:
    """Only fixed developer code and the bundled CSV are eligible for this demo."""
    if type(n_trials) is not int or not 1 <= n_trials <= 5:
        raise ValueError('The live demo permits 1–5 optimization trials')
    root = Path(root).resolve()
    report = ScientificWorkflowReport()
    try:
        inputs = root / 'inputs'
        inputs.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(__file__).parent / 'fixtures' / 'demo-study.csv', inputs / 'study.csv')
        csv_store = DatasetArtifactStore(root / 'csv-artifacts')
        figures = ArtifactStore(root / 'figure-artifacts')
        data_service = DatasetService(inputs, {'local-study': 'study.csv'}, artifact_store=csv_store)
        report.dataset_inspection = data_service.inspect({'dataset_id': 'local-study'})
        report.stage = 'dataset_processing'
        report.dataset_processing = data_service.process({
            'dataset_id': 'local-study', 'transformations': [
                {'operation': 'drop_missing', 'columns': ['feature', 'label']},
                {'operation': 'drop_duplicates'},
                {'operation': 'select_columns', 'columns': ['feature', 'label']},
            ],
        })
        processing = report.dataset_processing
        if processing.status != 'success':
            raise ValueError('Dataset processing failed')
        data = read_verified_artifact(csv_store, processing.artifact)
        report.artifacts_verified.append(artifact_verification(csv_store, processing.artifact))
        approved_input = root / 'approved-input.csv'
        approved_input.write_bytes(data)
        # Only this developer-authored code digest is accepted by the local transport.
        experiments = ExperimentService(TrustedDemoExecutor(
            {hashlib.sha256(EXPERIMENT_CODE.encode()).hexdigest()},
            work_root=root / 'workers', artifact_root=figures.root,
        ))
        dataset = ReplicationDataset(
            dataset_id='local-study', description='Bundled, intentionally simple local classification CSV',
            original_sha256=processing.provenance.source_sha256,
            processed=processing.artifact.to_reference(), transformations=processing.transformations,
        )
        report.stage = 'baseline_execution'
        report.baseline = experiments.run(ExperimentRequest(
            experiment_id='local-baseline', code=EXPERIMENT_CODE,
            parameters={'dataset_path': str(approved_input), 'max_depth': 1,
                        'min_samples_split': 2, 'validation_fraction': 1 / 3},
            random_seed=42, timeout_seconds=60, dataset_id=dataset.dataset_id,
            metadata={'processed_dataset': dataset.processed.model_dump(mode='json'),
                      'trusted_developer_authored_demo': True},
        ))
        baseline = report.baseline
        if baseline.status != 'success':
            raise ValueError('Local baseline execution failed')
        for artifact in baseline.artifacts:
            report.artifacts_verified.append(artifact_verification(figures, artifact))
        report.stage = 'replication'
        spec = ReplicationSpecification.model_validate({
            'paper': {'title': 'Measured local CSV decision-tree baseline',
                      'identifier': 'local-baseline:' + baseline.experiment_id,
                      'source_kind': 'local_baseline'},
            'experiment_id': 'local-reconstruction', 'experiment_title': 'Repeat the measured local baseline',
            'algorithm': 'Decision tree on a fixed stratified training/validation split',
            'dataset_required': True, 'dataset': dataset.model_dump(mode='json'),
            'required_dependencies': ['pandas', 'numpy', 'scikit-learn', 'matplotlib'],
            'published_parameters': baseline.parameters, 'parameters': baseline.parameters,
            'published_random_seed': baseline.random_seed, 'random_seed': baseline.random_seed,
            'evaluation_metrics': list(baseline.metrics),
            'published_metrics': [
                {'name': name, 'value': value, 'absolute_tolerance': 0.0, 'relative_tolerance': 0.0}
                for name, value in baseline.metrics.items()
            ],
            'code': EXPERIMENT_CODE, 'timeout_seconds': 60,
            'limitations': {'original_conditions_known': True, 'conditions_match_publication': True},
        })
        spec.approval = ResearcherApproval(approved=True, approved_by='trusted-local-demo',
                                            specification_sha256=specification_digest(spec))
        report.replication = ReplicationService(experiments).run(spec, available_dataset_ids={'local-study'})
        if report.replication.all_published_metrics_agree is not True:
            raise ValueError('Local baseline comparison did not complete with agreement')
        for artifact in report.replication.artifacts:
            report.artifacts_verified.append(artifact_verification(figures, artifact))
        report.stage = 'optimization'
        request = optimization_from_replication(
            report.replication, study_id='local-csv-tuning',
            search_space={'max_depth': {'type': 'int', 'low': 1, 'high': 4},
                          'min_samples_split': {'type': 'int', 'low': 2, 'high': 10}},
            objective_metric='accuracy', direction='maximize', n_trials=n_trials,
            max_duration_seconds=180, trial_timeout_seconds=60,
        )
        request.approval = ResearcherApproval(approved=True, approved_by='trusted-local-demo',
                                               specification_sha256=optimization_digest(request))
        iteration = IterationService(experiments)
        report.optimization = iteration.run(request, available_dataset_ids={'local-study'})
        report.stage = 'optimization_repeat'
        report.repeated_optimization = iteration.run(request, available_dataset_ids={'local-study'})
        report.repeatability = compare_optimization_runs(report.optimization, report.repeated_optimization)
        report.stage = 'artifact_verification'
        for study in (report.optimization, report.repeated_optimization):
            for trial in study.trials:
                for artifact in trial.artifacts:
                    report.artifacts_verified.append(artifact_verification(figures, artifact))
        if not report.repeatability.reproducible:
            raise ValueError('Optimization repeatability check failed')
        if not report.baseline.artifacts or any(not trial.artifacts for trial in report.optimization.trials):
            raise ValueError('Expected demonstration figures were not captured')
        report.status, report.stage = 'completed', 'completed'
        report.summary = (
            f'Dataset: {processing.original_summary.row_count} → {processing.final_summary.row_count} rows. '
            f'Local baseline accuracy: {baseline.metrics["accuracy"]!r}. '
            f'Baseline comparison: {report.replication.numerical_assessment}. '
            f'Best observed validation accuracy: {report.optimization.best_objective_value!r}. '
            f'Repeated optimization matched {n_trials} successful trials. '
            'Local demonstration only; numerical agreement is not independent scientific validation.'
        )
    except Exception as exc:
        report.error = ExecutionError(type=type(exc).__name__,
                                       message='Trusted workflow stopped; inspect the preserved stage reports.')
        report.summary = f'Workflow stopped at {report.stage}; partial evidence is retained.'
    return report


def main():
    root = Path('.runtime/end-to-end') / uuid4().hex
    report = run_demo(root)
    root.mkdir(parents=True, exist_ok=True)
    payload = tool_response(report)
    output = root / 'report.json'
    output.write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({'status': report.status, 'summary': report.summary,
                      'report_path': str(output),
                      'best_parameters': report.optimization.best_parameters if report.optimization else None,
                      'repeatability': report.repeatability.model_dump(mode='json') if report.repeatability else None,
                      'artifacts_verified': len(report.artifacts_verified)}, indent=2))
    return 0 if report.status == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
