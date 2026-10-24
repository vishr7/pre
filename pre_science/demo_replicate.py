"""Trusted local numerical baseline, not an independently reproduced publication."""

import json

from .experiment import ExperimentService
from .plots import ArtifactStore
from .replicate import ReplicationService, specification_digest
from .schemas import ReplicationSpecification, ResearcherApproval
from .worker import run_worker


def baseline_specification(mean_reference=30.0):
    """Fixed developer-authored code and an explicitly identified local baseline."""
    return ReplicationSpecification.model_validate({
        'paper': {'title': 'Local demonstration baseline: five-value population statistics',
                  'identifier': 'local-demo:population-statistics', 'source_kind': 'local_baseline'},
        'experiment_id': 'replicate-local-statistics',
        'experiment_title': 'Mean and population standard deviation of [10,20,30,40,50]',
        'algorithm': 'NumPy arithmetic mean and population standard deviation (ddof=0)',
        'dataset_required': False, 'required_dependencies': ['numpy', 'matplotlib'],
        'published_parameters': {'values': [10, 20, 30, 40, 50], 'ddof': 0},
        'parameters': {'values': [10, 20, 30, 40, 50], 'ddof': 0},
        'published_random_seed': 42, 'random_seed': 42,
        'evaluation_metrics': ['mean', 'std'],
        # Explicit local references: arithmetic mean 150/5; population std sqrt(200).
        'published_metrics': [
            {'name': 'mean', 'value': mean_reference, 'absolute_tolerance': 0.0, 'relative_tolerance': 0.0},
            {'name': 'std', 'value': 14.142135623730951, 'absolute_tolerance': 1e-12, 'relative_tolerance': 0.0},
        ],
        'limitations': {'original_conditions_known': True, 'conditions_match_publication': True},
        'code': '''
import numpy as np
import matplotlib.pyplot as plt
values = np.array(parameters["values"], dtype=float)
mean = float(np.mean(values))
std = float(np.std(values, ddof=parameters["ddof"]))
report_metric("mean", mean)
report_metric("std", std)
print("Mean:", mean)
print("Population standard deviation:", std)
plt.figure(figsize=(4, 3))
plt.plot(values, marker="o")
plt.title("Local demonstration data")
''',
    })


def main():
    store = ArtifactStore()

    class TrustedDemoExecutor:
        def execute(self, request):
            return run_worker(request, artifact_store=store)

    service = ReplicationService(ExperimentService(TrustedDemoExecutor()))
    reports = {}
    for label, reference in (('matching_local_baseline', 30.0), ('intentionally_changed_reference', 31.0)):
        proposal = baseline_specification(reference)
        proposal.approval = ResearcherApproval(
            approved=True, approved_by='trusted-local-demo',
            specification_sha256=specification_digest(proposal),
        )
        report = service.run(proposal)
        if report.execution_status != 'success':
            raise RuntimeError(report.model_dump_json())
        # Verify actual figure handoff, without embedding PNG bytes in the report.
        for artifact in report.artifacts:
            assert len(store.retrieve(artifact.artifact_id)) == artifact.size_bytes
        reports[label] = report.model_dump(mode='json')
    assert reports['matching_local_baseline']['all_published_metrics_agree'] is True
    assert reports['intentionally_changed_reference']['all_published_metrics_agree'] is False
    print(json.dumps(reports, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
