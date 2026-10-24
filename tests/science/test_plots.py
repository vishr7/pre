"""Real PNG tests with trusted code only; no claims of security isolation."""

import hashlib
import io
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use('Agg')
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import pytest
from pydantic import ValidationError

from pre_science.experiment import ExperimentService
from pre_science.plots import ArtifactStore, FigureLimits, png_dimensions
from pre_science.schemas import ExperimentRequest, ExperimentResult, ExecutionOutput
from pre_science.worker import run_worker


PLOT = '''
import matplotlib.pyplot as plt
plt.figure(figsize=(4, 3))
plt.plot([1, 2, 3], [1, 4, 9])
plt.title("Trusted test")
plt.show()
report_metric("score", 0.91)
'''


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(tmp_path / 'artifacts')


def execute(store, code=PLOT, experiment_id='figure-test', **kwargs):
    return run_worker(ExperimentRequest(experiment_id=experiment_id, code=code),
                      artifact_store=store, **kwargs)


def test_real_png_metadata_retrieval_and_serialization(store):
    result = execute(store)
    assert result.status == 'success'
    assert result.metrics == {'score': 0.91}
    assert result.execution_metadata['artifact_errors'] == []
    artifact, = result.artifacts
    assert artifact.experiment_id == 'figure-test'
    assert artifact.artifact_type == 'figure'
    assert artifact.mime_type == 'image/png'
    assert not Path(artifact.artifact_reference).is_absolute()
    data = store.retrieve(artifact.artifact_id)
    assert len(data) == artifact.size_bytes
    assert hashlib.sha256(data).hexdigest() == artifact.sha256
    assert png_dimensions(data) == (artifact.width, artifact.height) == (400, 300)
    pixels = mpimg.imread(io.BytesIO(data), format='png')
    assert pixels.shape[:2] == (300, 400)
    assert len(list(store.root.rglob('*.png'))) == 1
    assert not plt.get_fignums()
    assert ExecutionOutput.model_validate_json(result.model_dump_json()) == result


def test_multiple_figures_and_cleanup(store):
    result = execute(store, PLOT + '\nplt.figure()\nplt.plot([2, 1])')
    assert len(result.artifacts) == 2
    first, second = result.artifacts
    assert first.artifact_id != second.artifact_id
    assert first.experiment_id == second.experiment_id == 'figure-test'
    store.cleanup(first.artifact_id)
    with pytest.raises(FileNotFoundError):
        store.retrieve(first.artifact_id)
    assert store.retrieve(second.artifact_id)
    store.cleanup(second.artifact_id)
    store.cleanup(second.artifact_id)  # Idempotent acknowledgement/retry.
    assert list(store.root.iterdir()) == []
    assert plt.get_fignums() == []


def test_no_figures(store):
    result = execute(store, 'report_metric("value", 2)')
    assert result.artifacts == []
    assert result.metrics == {'value': 2.0}
    assert list(store.root.iterdir()) == []


def test_experiment_and_repeated_run_separation(store):
    first = execute(store, experiment_id='../untrusted/name')
    second = execute(store, experiment_id='other')
    repeat = execute(store, experiment_id='../untrusted/name')
    assert first.artifacts[0].experiment_id == '../untrusted/name'
    identifiers = [r.artifacts[0].artifact_id for r in (first, second, repeat)]
    assert len(set(identifiers)) == 3
    assert len({i.split('-')[0] for i in identifiers}) == 3
    assert len(list(store.root.iterdir())) == 3


def test_figure_limit_closes_even_skipped_figures(store):
    result = execute(store, PLOT + '\nplt.figure()\nplt.figure()',
                     figure_limits=FigureLimits(max_figures=1))
    assert result.status == 'success'
    assert len(result.artifacts) == 1
    assert 'Figure limit exceeded' in result.execution_metadata['artifact_errors'][0]
    assert not plt.get_fignums()


@pytest.mark.parametrize('limits', [FigureLimits(max_dimension=100),
                                      FigureLimits(max_pixels=100),
                                      FigureLimits(max_size_bytes=1024)])
def test_dimension_and_size_limits(store, limits):
    result = execute(store, figure_limits=limits)
    assert result.status == 'success'
    assert result.artifacts == []
    assert result.execution_metadata['artifact_errors']
    assert not list(store.root.rglob('*.png'))
    assert not plt.get_fignums()


def test_export_failure_preserves_other_figures_and_metrics(store):
    savefig = Figure.savefig

    def fail_first(figure, *args, **kwargs):
        if figure.number == 1:
            raise OSError('Simulated export failure')
        return savefig(figure, *args, **kwargs)

    with patch.object(Figure, 'savefig', fail_first):
        result = execute(store, PLOT + '\nplt.figure()\nplt.plot([1, 2])')
    assert result.status == 'success'
    assert result.metrics == {'score': 0.91}
    assert len(result.artifacts) == 1
    assert 'Simulated export failure' in result.execution_metadata['artifact_errors'][0]
    assert not plt.get_fignums()


def test_code_error_preserves_partial_figures(store):
    result = execute(store, PLOT + '\nraise RuntimeError("trusted error")')
    assert result.status == 'error'
    assert result.error.type == 'RuntimeError'
    assert len(result.artifacts) == 1
    assert not plt.get_fignums()


@pytest.mark.parametrize('reference', ['../secret', '/etc/passwd', 'C:\\secret',
                                         '', 'a' * 64, 'a' * 32 + '-../secret'])
def test_invalid_references(store, reference):
    with pytest.raises(ValueError):
        store.retrieve(reference)
    with pytest.raises(ValueError):
        store.cleanup(reference)


def test_symlink_rejection(store, tmp_path):
    result = execute(store)
    artifact = result.artifacts[0]
    run, token = artifact.artifact_id.split('-')
    target = store.root / run / (token + '.png')
    outside = tmp_path / 'outside.png'
    outside.write_bytes(target.read_bytes())
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip('OS does not permit creating symlinks for this user')
    with pytest.raises(ValueError):
        store.retrieve(artifact.artifact_id)
    with pytest.raises(ValueError):
        store.cleanup(artifact.artifact_id)
    assert outside.exists()


def test_orchestration_preserves_artifacts_and_rng(store):
    class TrustedTestExecutor:
        def execute(self, request):
            return run_worker(request, artifact_store=store)

    random_code = 'import numpy as np\nreport_metric("rng", np.random.random())\n'
    service = ExperimentService(TrustedTestExecutor())
    base = service.run(ExperimentRequest(experiment_id='base', code=random_code, random_seed=42))
    plotted = service.run(ExperimentRequest(
        experiment_id='plotted', code=random_code + PLOT, random_seed=42))
    assert plotted.metrics['rng'] == base.metrics['rng']
    assert len(plotted.artifacts) == 1
    assert plotted.random_seed == 42
    assert len(plotted.execution_metadata['code_sha256']) == 64
    assert plotted.execution_metadata['dependencies']['matplotlib']
    assert ExperimentResult.model_validate_json(plotted.model_dump_json()) == plotted


def test_store_failure_is_visible_and_closes_figures(store):
    with patch.object(ArtifactStore, 'save', side_effect=OSError('Disk full')):
        result = execute(store)
    assert result.status == 'success'
    assert result.artifacts == []
    assert 'Disk full' in result.execution_metadata['artifact_errors'][0]
    assert not plt.get_fignums()


def test_invalid_limits():
    with pytest.raises(ValidationError):
        FigureLimits(max_figures=0)


def test_legacy_artifact_contract_still_accepted():
    result = ExecutionOutput(status='success', exit_code=0,
                             artifacts=[{'name': 'legacy', 'media_type': 'text/plain', 'path': 'x'}])
    assert result.artifacts[0].name == 'legacy'
