"""Trusted local Iris tuning demo, not a reproduction or independent test score.

The local executor below is for developer-authored fixtures only. Never connect
it to user/Gemini proposals: a subprocess is NOT a security sandbox.
"""

import json
import hashlib

from .experiment import ExperimentService
from .iterate import IterationService, optimization_digest
from .integration import compare_optimization_runs
from .schemas import OptimizationRequest, ResearcherApproval
from .trusted_demo import TrustedDemoExecutor as _TrustedDemoExecutor


def iris_request() -> OptimizationRequest:
    return OptimizationRequest.model_validate({
        'study_id': 'local-iris-tree-demo', 'experiment_id': 'local-iris-tree',
        'base_parameters': {'validation_fraction': 0.3},
        'search_space': {
            'max_depth': {'type': 'int', 'low': 1, 'high': 6},
            'min_samples_split': {'type': 'int', 'low': 2, 'high': 10},
        },
        'objective_metric': 'accuracy', 'direction': 'maximize', 'n_trials': 6,
        'max_duration_seconds': 120, 'trial_timeout_seconds': 20, 'random_seed': 42,
        'code': '''
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score
assert "previous_trial_value" not in globals()
previous_trial_value = True
x, y = load_iris(return_X_y=True)
x_train, x_validation, y_train, y_validation = train_test_split(
    x, y, test_size=parameters["validation_fraction"], random_state=random_seed, stratify=y)
model = DecisionTreeClassifier(max_depth=parameters["max_depth"],
    min_samples_split=parameters["min_samples_split"], random_state=random_seed)
model.fit(x_train, y_train)
accuracy = float(accuracy_score(y_validation, model.predict(x_validation)))
report_metric("accuracy", accuracy)
print("Local Iris validation accuracy:", accuracy)
''',
    })


def main():
    request = iris_request()
    request.approval = ResearcherApproval(
        approved=True, approved_by='trusted-local-demo',
        specification_sha256=optimization_digest(request),
    )
    service = IterationService(ExperimentService(_TrustedDemoExecutor({hashlib.sha256(request.code.encode()).hexdigest()})))
    first, repeated = service.run(request), service.run(request)
    assessment = compare_optimization_runs(first, repeated)
    reproducible = assessment.reproducible
    # Preserve evidence even when runtime failures make the repeat check fail.
    print(json.dumps({
        'description': 'Local Iris validation-set tuning; not a published reproduction or independent test result',
        'first_run': first.model_dump(mode='json'),
        'repeated_run': repeated.model_dump(mode='json'), 'reproducible': reproducible,
        'repeatability': assessment.model_dump(mode='json'),
    }, indent=2, allow_nan=False))
    if first.status != 'completed' or repeated.status != 'completed':
        raise RuntimeError('Trusted demo did not complete both studies; inspect the emitted reports')
    if not reproducible:
        raise RuntimeError('Seeded trials differed; inspect the emitted execution and objective history')


if __name__ == '__main__':
    main()
