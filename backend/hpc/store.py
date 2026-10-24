"""Session/job metadata store. In-memory today; swap InMemoryStore for a Postgres one later.

Only serializable metadata lives here. Live SSH connections stay in the
SessionManager (they can't be persisted), and credentials are never stored.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import AuthPrompt, SessionState


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SessionRecord:
    session_id: str
    host: str
    port: int
    username: str
    jump_host: str | None = None
    status: SessionState = "connecting"
    created_at: datetime = field(default_factory=utcnow)
    connected_at: datetime | None = None
    base_dir: str | None = None
    error: str | None = None
    hop: str | None = None
    instructions: str | None = None
    prompts: list[AuthPrompt] = field(default_factory=list)


@dataclass
class JobRecord:
    job_id: str
    session_id: str
    backend: str
    job_name: str
    project: str
    work_dir: str
    script_path: str
    array_size: int | None
    pid: int | None = None
    gpu: int | None = None
    submitted_at: datetime = field(default_factory=utcnow)


class Store(ABC):
    @abstractmethod
    async def save_session(self, record: SessionRecord) -> None: ...

    @abstractmethod
    async def get_session(self, session_id: str) -> SessionRecord | None: ...

    @abstractmethod
    async def list_sessions(self) -> list[SessionRecord]: ...

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """Delete the session and its job records."""

    @abstractmethod
    async def save_job(self, record: JobRecord) -> None: ...

    @abstractmethod
    async def get_job(self, session_id: str, job_id: str) -> JobRecord | None: ...

    @abstractmethod
    async def list_jobs(self, session_id: str) -> list[JobRecord]: ...


class InMemoryStore(Store):
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._jobs: dict[tuple[str, str], JobRecord] = {}

    async def save_session(self, record: SessionRecord) -> None:
        self._sessions[record.session_id] = record

    async def get_session(self, session_id: str) -> SessionRecord | None:
        return self._sessions.get(session_id)

    async def list_sessions(self) -> list[SessionRecord]:
        return list(self._sessions.values())

    async def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        for key in [k for k in self._jobs if k[0] == session_id]:
            del self._jobs[key]

    async def save_job(self, record: JobRecord) -> None:
        self._jobs[(record.session_id, record.job_id)] = record

    async def get_job(self, session_id: str, job_id: str) -> JobRecord | None:
        return self._jobs.get((session_id, job_id))

    async def list_jobs(self, session_id: str) -> list[JobRecord]:
        return [j for (sid, _), j in self._jobs.items() if sid == session_id]
