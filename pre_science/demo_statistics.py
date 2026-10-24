"""Actual trusted Iris depth comparisons on explicitly matched stratified splits."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .demo_robustness import CODE
from .experiment import ExperimentService
from .robustness import RobustnessRequest, RobustnessService, robustness_digest
from .schemas import ResearcherApproval
from .statistics import analyze_statistics, statistics_from_robustness
from .trusted_demo import TrustedDemoExecutor


def main():
    root = Path('.runtime/statistics') / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    service = RobustnessService(ExperimentService(TrustedDemoExecutor(
        {hashlib.sha256(CODE.encode()).hexdigest()}, work_root=root / 'workers', artifact_root=root / 'figures')))
    reports = []
    for depth in (1, 3):
        request = RobustnessRequest(study_id=f'iris-depth-{depth}', experiment_id=f'tree-depth-{depth}',
            code=CODE, parameters={'max_depth': depth}, seeds=[1, 7, 21, 42, 123], metrics=['accuracy'],
            max_duration_seconds=180, source={'dataset': 'sklearn bundled Iris',
                'conditions': 'Same seed, stratified train_test_split, test_size=0.3 for both methods'})
        request.approval = ResearcherApproval(approved=True, approved_by='trusted-local-demo',
            specification_sha256=robustness_digest(request))
        report = service.run(request)
        reports.append(report)
        # Preserve actual execution evidence even if a subsequent stage fails.
        (root / f'depth-{depth}.json').write_text(report.model_dump_json(indent=2), encoding='utf-8')
    conditions = {seed: f'iris-stratified-test-0.3-seed-{seed}' for seed in reports[0].requested_seeds}
    request = statistics_from_robustness(*reports, analysis_id='iris-depth-paired-comparison', metric='accuracy',
        test='paired_t', paired=True, conditions_a=conditions, conditions_b=conditions, units='fraction correct')
    result = analyze_statistics(request)
    (root / 'report.json').write_text(result.model_dump_json(indent=2), encoding='utf-8')
    print(json.dumps({'report_path': str(root / 'report.json'), 'observations_a': request.observations_a,
        'observations_b': request.observations_b, 'summary': result.summary,
        'mean_difference_A_minus_B': result.estimated_mean_difference,
        'confidence_interval': result.confidence_interval.model_dump(mode='json'),
        'effect_size': result.effect_size.model_dump(mode='json'),
        'limitation': 'Matched splits justify pair correspondence; overlapping Iris data do not establish independent pairs. Inference is illustrative.'}, indent=2))


if __name__ == '__main__':
    main()
