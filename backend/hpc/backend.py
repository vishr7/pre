"""Interfaces and HTTP-mapped errors.

Two layers:
- Transport (HPCBackend -> HPCConnection): how we reach the machine. Real asyncssh
  (optionally through a jump host) or the mock machine.
- Compute (ComputeBackend): how jobs run there. WorkstationBackend (background
  processes tracked by PID) or SlurmBackend (sbatch/squeue/sacct).
Any compute backend works over any transport, so mock mode exercises the real job logic.
"""

import shlex
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException

from .models import AuthPrompt, ConnectRequest, FileInfo, GPUList, JobSpec, JobStatus, JobSubmitResponse


class HPCError(HTTPException):
    """Base error; subclasses fix the HTTP status so FastAPI renders them directly."""

    status_code = 500

    def __init__(self, detail: Any):
        super().__init__(status_code=type(self).status_code, detail=detail)


class InvalidRequest(HPCError):
    status_code = 400


class AuthFailed(HPCError):
    status_code = 401


class Forbidden(HPCError):
    """Command outside the allowlist, or a remote permission error."""

    status_code = 403


class NotFound(HPCError):
    status_code = 404


class SessionNotReady(HPCError):
    status_code = 409


class GPUBusy(HPCError):
    """detail is {"message": str, "gpus": [GPUInfo, ...]}."""

    status_code = 409


class PayloadTooLarge(HPCError):
    status_code = 413


class SlurmError(HPCError):
    status_code = 422


class NotSupported(HPCError):
    status_code = 501


class HostUnreachable(HPCError):
    status_code = 502


class RemoteTimeout(HPCError):
    status_code = 504


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int | None


# Called when a server asks keyboard-interactive questions (e.g. Duo).
# Receives (hop host, instructions, prompts) and returns one answer per prompt.
ChallengeHandler = Callable[[str, str, list[AuthPrompt]], Awaitable[list[str]]]


class HPCConnection(ABC):
    """One live, reusable connection to the remote machine."""

    @abstractmethod
    async def run(self, command: str, timeout: float) -> CommandResult:
        """Run a shell command (through a login shell) and capture its output."""

    @abstractmethod
    def stream(self, command: str, timeout: float) -> AsyncIterator[tuple[str, Any]]:
        """Run a command, yielding ("output", text) chunks (stdout+stderr) then ("exit", code)."""

    @abstractmethod
    async def realpath(self, path: str) -> str: ...

    @abstractmethod
    async def makedirs(self, path: str) -> None: ...

    @abstractmethod
    async def write_file(self, path: str, data: bytes) -> None: ...

    @abstractmethod
    async def read_file(self, path: str, max_bytes: int) -> bytes:
        """Read a whole file; raise PayloadTooLarge above max_bytes, NotFound if missing."""

    @abstractmethod
    async def read_from(self, path: str, offset: int, max_bytes: int = 65536) -> bytes:
        """Read up to max_bytes starting at offset; b"" if the file doesn't exist yet."""

    @abstractmethod
    async def listdir(self, path: str) -> list[FileInfo]: ...

    @abstractmethod
    def is_alive(self) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...


class HPCBackend(ABC):
    @abstractmethod
    async def connect(self, req: ConnectRequest, challenge: ChallengeHandler) -> HPCConnection:
        """Open a connection (req.host/jump_host already resolved), relaying prompts to `challenge`."""


@dataclass
class JobContext:
    """What a compute backend needs to know about the session it runs in."""

    session_id: str
    username: str
    base_dir: str
    our_pids: set[int] = field(default_factory=set)

    def project_dir(self, project: str) -> str:
        return f"{self.base_dir}/{project}"


@dataclass
class JobRecordData:
    """Fields a backend wants persisted for a submitted job (see store.JobRecord)."""

    job_id: str
    work_dir: str
    script_path: str
    array_size: int | None
    pid: int | None = None
    gpu: int | None = None


class ComputeBackend(ABC):
    name: str

    @abstractmethod
    async def base_dir(self, conn: HPCConnection, username: str) -> str:
        """Resolve (and create if needed) the root directory for this user's projects."""

    @abstractmethod
    def check_command(self, argv: list[str], ctx: JobContext) -> list[str]:
        """Enforce the /exec allowlist; may rewrite paths. Raise Forbidden to refuse."""

    @abstractmethod
    async def submit_job(self, conn: HPCConnection, ctx: JobContext,
                         spec: JobSpec) -> tuple[JobSubmitResponse, JobRecordData | None]:
        """Render the job script and (unless dry_run) launch it."""

    @abstractmethod
    async def job_status(self, conn: HPCConnection, job_id: str, record) -> JobStatus:
        """`record` is the store.JobRecord, or None for jobs PRE didn't submit."""

    @abstractmethod
    async def cancel(self, conn: HPCConnection, job_id: str, record) -> None: ...

    @abstractmethod
    def log_path(self, record, task: int) -> str:
        """Log file to tail for the stream endpoint."""

    async def gpus(self, conn: HPCConnection, ctx: JobContext) -> GPUList:
        raise NotSupported(f"GPU checks are not available on the {self.name} backend")


def job_command(spec: JobSpec, python: str = "python") -> str:
    """The shell command a job runs: spec.command, or python on the job's script, plus args."""
    args = " ".join(shlex.quote(a) for a in spec.args)
    if spec.command:
        base = spec.command
    else:
        where = "$PRE_JOB_DIR" if spec.script is not None else "$PRE_PROJECT_DIR"
        base = f'{python} "{where}/{spec.script_filename}"'
    return f"{base} {args}".rstrip()
