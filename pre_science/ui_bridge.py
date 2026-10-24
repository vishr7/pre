"""Local IDE adapter: compare reported metrics or execute a fixed trusted demo."""
import hashlib
import json
import sys
from .replicate import compare_metrics, ReplicationService, specification_digest
from .schemas import PublishedMetric, ReplicationReport, ResearcherApproval
from .integration import tool_response


def handle(data):
    action = data.get('action')
    if action == 'syntax':
        import ast
        code = data.get('code')
        if not isinstance(code, str) or len(code) > 100000:
            raise ValueError('Provide Python source under 100 KB.')
        try:
            ast.parse(code)
            return {'valid': True}
        except SyntaxError as error:
            return {'valid': False, 'error': f'Line {error.lineno}: {error.msg}'}
    if action == 'compare':
        metrics = data.get('published_metrics')
        actual = data.get('reproduced_metrics')
        if not isinstance(metrics, list) or not 1 <= len(metrics) <= 100 or not isinstance(actual, dict):
            raise ValueError('Provide 1–100 reference metrics and your measured results.')
        references = [PublishedMetric.model_validate(item) for item in metrics]
        if len({item.name for item in references}) != len(references):
            raise ValueError('Metric names must be unique.')
        comparisons = compare_metrics(references, actual)
        return {'summary': 'Compared supplied measurements. No experiment was executed.',
                'comparisons': [item.model_dump(mode='json') for item in comparisons],
                'source_kind': 'user_measurements'}
    if action == 'report':
        report = ReplicationReport.model_validate(data.get('report'))
        return {'summary': report.summary, 'comparisons': [item.model_dump(mode='json') for item in report.comparisons],
                'scientific': report.model_dump(mode='json'), 'source_kind': 'imported_report'}
    if action == 'demo':
        from .demo_replicate import baseline_specification
        from .trusted_demo import TrustedDemoExecutor
        from .experiment import ExperimentService
        # Never accept client code, parameters, approval, or paths for this action.
        proposal = baseline_specification()
        proposal.approval = ResearcherApproval(approved=True, approved_by='local-fixed-demo',
                                                specification_sha256=specification_digest(proposal))
        executor = TrustedDemoExecutor([hashlib.sha256(proposal.code.encode()).hexdigest()])
        report = ReplicationService(ExperimentService(executor)).run(proposal)
        return {**tool_response(report), 'summary': report.summary,
                'comparisons': [item.model_dump(mode='json') for item in report.comparisons],
                'source_kind': 'local_baseline'}
    raise ValueError('Choose compare, report, or demo.')

if __name__ == '__main__':
    try:
        print(json.dumps(handle(json.load(sys.stdin)), allow_nan=False))
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        sys.exit(1)
