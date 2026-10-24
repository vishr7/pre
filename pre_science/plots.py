"""Bounded PNG capture and local handoff. Not an isolation/security sandbox."""

import hashlib
import io
import os
from pathlib import Path
import re
import stat
import struct
from uuid import uuid4

from pydantic import Field

from .schemas import FigureArtifact, Model


class FigureLimits(Model):
    max_figures: int = Field(default=8, ge=1, le=32)
    max_size_bytes: int = Field(default=10_000_000, ge=1024, le=50_000_000)
    max_dimension: int = Field(default=4096, ge=1, le=8192)
    max_pixels: int = Field(default=16_000_000, ge=1, le=32_000_000)
    dpi: int = Field(default=100, ge=25, le=300)


class _BoundedBuffer(io.BytesIO):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise ValueError('PNG exceeds the configured file-size limit')
        return super().write(data)


class ArtifactStore:
    """Controlled output root shared/mounted by the worker and backend adapter.

    IDs encode random run and file tokens, never experiment-provided paths.
    Files persist until cleanup is explicitly called after successful handoff.
    The root must not be writable by other concurrent/untrusted processes.
    """

    def __init__(self, root: str | Path | None = None):
        supplied = Path(root if root is not None else os.environ.get(
            'PRE_SCIENCE_ARTIFACT_ROOT', '.runtime/science-artifacts'))
        # Reject symlinks in configured paths rather than silently following them.
        absolute = supplied.absolute()
        for component in (absolute, *absolute.parents):
            if component.is_symlink():
                raise ValueError('Artifact directories cannot contain symlinks')
        self.root = absolute.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, artifact_id: str) -> Path:
        if not isinstance(artifact_id, str) or not re.fullmatch(
                r'[0-9a-f]{32}-[0-9a-f]{32}', artifact_id):
            raise ValueError('Invalid artifact identifier')
        run, token = artifact_id.split('-')
        target = self.root / run / (token + '.png')
        if self.root.is_symlink() or target.parent.is_symlink() or target.is_symlink():
            raise ValueError('Artifact paths cannot contain symlinks')
        if target.resolve().parent.parent != self.root:
            raise ValueError('Artifact must stay within its output directory')
        return target

    def save(self, run_id: str, experiment_id: str, data: bytes) -> FigureArtifact:
        artifact_id = f'{run_id}-{uuid4().hex}'
        target = self._path(artifact_id)
        width, height = png_dimensions(data)
        target.parent.mkdir(exist_ok=True)
        created = False
        try:
            with target.open('xb') as stream:
                created = True
                stream.write(data)
        except BaseException:
            if created and target.is_file() and not target.is_symlink():
                target.unlink()
            raise
        return FigureArtifact(
            artifact_id=artifact_id, experiment_id=experiment_id,
            filename=target.name, size_bytes=len(data), width=width, height=height,
            sha256=hashlib.sha256(data).hexdigest(), artifact_reference=artifact_id,
        )

    def retrieve(self, artifact_id: str) -> bytes:
        """Retrieve a regular PNG by opaque ID, not by a supplied filesystem path."""
        target = self._path(artifact_id)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
        with os.fdopen(os.open(target, flags), 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 50_000_000:
                raise ValueError('Artifact is not a bounded regular file')
            data = stream.read(50_000_001)
        if len(data) > 50_000_000:
            raise ValueError('Artifact exceeds retrieval size limit')
        png_dimensions(data)
        return data

    def cleanup(self, artifact_id: str) -> None:
        """Delete only this artifact; call after persistence, never before upload."""
        target = self._path(artifact_id)
        target.unlink(missing_ok=True)
        try:
            target.parent.rmdir()  # Only remove an empty run directory.
        except (FileNotFoundError, OSError):
            pass


def png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise ValueError('Artifact is not a PNG')
    width, height = struct.unpack('>II', data[16:24])
    if not width or not height:
        raise ValueError('PNG dimensions must be positive')
    return width, height


def capture_figures(experiment_id: str, store: ArtifactStore,
                    limits: FigureLimits) -> tuple[list[FigureArtifact], list[str]]:
    """Capture active figures in figure-number order; always close every figure.

    Export failures leave other figures available for capture. The worker reports
    these errors separately without overwriting numerical execution outcomes.
    """
    import matplotlib.pyplot as plt

    artifacts, errors = [], []
    run_id = uuid4().hex
    try:
        numbers = plt.get_fignums()
        if len(numbers) > limits.max_figures:
            errors.append(f'Figure limit exceeded: capturing {limits.max_figures} of {len(numbers)}')
        for number in numbers[:limits.max_figures]:
            try:
                figure = plt.figure(number)
                dimensions = figure.get_size_inches() * limits.dpi
                if (any(not 1 <= value <= limits.max_dimension for value in dimensions)
                        or dimensions.prod() > limits.max_pixels):
                    raise ValueError('Figure exceeds configured image-dimension limits')
                with _BoundedBuffer(limits.max_size_bytes) as buffer:
                    figure.savefig(buffer, format='png', dpi=limits.dpi,
                                   bbox_inches=None, transparent=False)
                    data = buffer.getvalue()
                width, height = png_dimensions(data)
                if (max(width, height) > limits.max_dimension
                        or width * height > limits.max_pixels):
                    raise ValueError('PNG exceeds configured image-dimension limits')
                artifacts.append(store.save(run_id, experiment_id, data))
            except Exception as exc:
                errors.append(f'Figure {number}: {type(exc).__name__}: {exc}')
    finally:
        plt.close('all')
    return artifacts, errors
