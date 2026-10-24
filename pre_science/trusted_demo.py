"""Fixed-code local demo transport to the EXISTING worker CLI. NOT a sandbox.

Never wire this into routes accepting user/Gemini code. Hash allowlisting prevents
accidental execution of other code; it does not establish security or approval.
"""

from collections.abc import Collection
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock
import time

from .contracts import ExecutionFailure
from .schemas import ExecutionError, ExecutionOutput


class TrustedDemoExecutor:
    def __init__(self, allowed_code_hashes: Collection[str], *,
                 work_root='.runtime/trusted-demo-workers', artifact_root='.runtime/science-artifacts'):
        self.allowed = frozenset(allowed_code_hashes)
        self.work_root = Path(work_root).resolve()
        self.artifact_root = Path(artifact_root).resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def execute(self, request):
        if hashlib.sha256(request.code.encode()).hexdigest() not in self.allowed:
            raise ExecutionFailure('Code is not a registered developer-authored demonstration')
        if not self._lock.acquire(blocking=False):
            raise ExecutionFailure('Trusted demo execution is sequential only')
        started = time.monotonic()
        try:
            with TemporaryDirectory(prefix='job-', dir=self.work_root) as job:
                allowed = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR',
                           'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'LANG', 'LC_ALL'}
                environment = {name: value for name, value in os.environ.items() if name.upper() in allowed}
                environment.update(
                    PYTHONIOENCODING='utf-8', PYTHONNOUSERSITE='1',
                    PYTHONPATH=str(Path(__file__).resolve().parents[1]),
                    MPLCONFIGDIR=str(self.work_root / 'matplotlib'),
                    PRE_SCIENCE_ARTIFACT_ROOT=str(self.artifact_root),
                    OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1',
                )
                try:
                    process = subprocess.run(
                        [sys.executable, '-m', 'pre_science.worker'], input=request.model_dump_json(),
                        text=True, encoding='utf-8', capture_output=True, timeout=request.timeout_seconds,
                        cwd=job, env=environment, check=False,
                    )
                except subprocess.TimeoutExpired:
                    return ExecutionOutput(
                        status='timeout', exit_code=124, execution_time=time.monotonic() - started,
                        error=ExecutionError(type='Timeout', message='Trusted local trial exceeded its timeout'),
                    )
                try:
                    output = ExecutionOutput.model_validate_json(process.stdout)
                except ValueError:
                    raise ExecutionFailure('Trusted worker returned invalid structured output') from None
                if process.returncode != output.exit_code:
                    raise ExecutionFailure('Trusted worker exit status did not match its output')
                output.execution_metadata['trusted_demo_transport'] = {
                    'fresh_working_directory': True, 'fresh_process': True,
                    'wall_seconds': time.monotonic() - started,
                }
                return output
        finally:
            self._lock.release()
