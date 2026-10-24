"""Real asyncssh transport (direct or through a jump host) plus the SessionManager.

Security: credentials and 2FA answers only live in local variables / the asyncssh
client objects for the duration of the handshake. Nothing secret is logged or stored.
"""

import asyncio
import logging
import os
import re
import secrets
import shlex
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath

import asyncssh

from .backend import (
    AuthFailed, ChallengeHandler, CommandResult, ComputeBackend, Forbidden, HostUnreachable,
    HPCBackend, HPCConnection, HPCError, InvalidRequest, JobContext, NotFound, PayloadTooLarge,
    RemoteTimeout, SessionNotReady,
)
from .config import HPCSettings
from .models import AuthPrompt, ConnectRequest, ConnectResponse, FileInfo, SessionStatus
from .store import SessionRecord, Store, utcnow

log = logging.getLogger("pre.hpc")

MAX_OUTPUT_CHARS = 1_000_000
MAX_KBDINT_ATTEMPTS = 5

# Commands from POST /exec must be a single simple command: no chaining, redirection,
# substitution, globs or variables. The compute backend then applies its allowlist.
_SHELL_META = re.compile(r"[;&|`$<>(){}\n\r\\!*?\[\]~]")


def parse_user_command(command: str) -> list[str]:
    if _SHELL_META.search(command):
        raise Forbidden("shell operators, globs, and variables are not allowed in commands")
    try:
        argv = shlex.split(command)
    except ValueError as e:
        raise InvalidRequest(f"could not parse command: {e}")
    if not argv:
        raise InvalidRequest("empty command")
    return argv


def safe_relpath(path: str) -> str:
    """Normalize a user-supplied relative path; reject absolute paths and '..'."""
    path = path.strip().strip("/") if path else ""
    if not path:
        return ""
    if "\\" in path or "\x00" in path or any(ord(c) < 32 for c in path):
        raise InvalidRequest("invalid characters in path")
    parts = PurePosixPath(path).parts
    if any(p in ("..", ".") for p in parts):
        raise InvalidRequest("path must not contain '.' or '..' segments")
    return "/".join(parts)


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT_CHARS else text[:MAX_OUTPUT_CHARS] + "\n[truncated]"


# ---------------------------------------------------------------------------
# asyncssh transport
# ---------------------------------------------------------------------------

class _Client(asyncssh.SSHClient):
    """Answers password prompts itself and forwards every other prompt (Duo etc.)."""

    def __init__(self, password: str | None, challenge: ChallengeHandler, hop: str):
        self._password = password
        self._password_sent = False
        self._challenge = challenge
        self._hop = hop
        self._kbdint_attempts = 0
        self.lost = False

    def connection_lost(self, exc: Exception | None) -> None:
        self.lost = True

    def password_auth_requested(self) -> str | None:
        if self._password is None or self._password_sent:
            return None
        self._password_sent = True
        return self._password

    def kbdint_auth_requested(self) -> str | None:
        # Servers may keep offering kbdint after a rejection; don't retry forever.
        self._kbdint_attempts += 1
        return "" if self._kbdint_attempts <= MAX_KBDINT_ATTEMPTS else None

    async def kbdint_challenge_received(self, name, instructions, lang, prompts):
        if not prompts:
            return []  # informational round (banner text)
        if (len(prompts) == 1 and not prompts[0][1] and "password" in prompts[0][0].lower()
                and self._password is not None and not self._password_sent):
            self._password_sent = True
            return [self._password]
        return await self._challenge(
            self._hop,
            "\n".join(x for x in (name, instructions) if x),
            [AuthPrompt(prompt=p, echo=e) for p, e in prompts],
        )


@contextmanager
def _sftp_errors(path: str):
    try:
        yield
    except asyncssh.SFTPNoSuchFile:
        raise NotFound(f"remote path not found: {path}")
    except asyncssh.SFTPPermissionDenied:
        raise Forbidden(f"permission denied: {path}")
    except asyncssh.SFTPError as e:
        raise HPCError(f"SFTP error on {path}: {e.reason}")
    except (asyncssh.Error, OSError):
        raise HostUnreachable("connection to the remote machine was lost")


class AsyncSSHConnection(HPCConnection):
    def __init__(self, conn: asyncssh.SSHClientConnection, client: _Client,
                 jump: asyncssh.SSHClientConnection | None = None, jump_client: _Client | None = None):
        self._conn = conn
        self._client = client
        self._jump = jump
        self._jump_client = jump_client
        self._sftp: asyncssh.SFTPClient | None = None
        self._sftp_lock = asyncio.Lock()

    async def _get_sftp(self) -> asyncssh.SFTPClient:
        async with self._sftp_lock:
            if self._sftp is None:
                try:
                    self._sftp = await self._conn.start_sftp_client()
                except (asyncssh.Error, OSError):
                    raise HostUnreachable("could not open an SFTP channel")
            return self._sftp

    async def run(self, command: str, timeout: float) -> CommandResult:
        # Login shell so user tools (pyenv, Lmod's `module`) are on PATH.
        try:
            r = await self._conn.run(f"bash -lc {shlex.quote(command)}", check=False, timeout=timeout)
        except asyncssh.TimeoutError:
            raise RemoteTimeout(f"command timed out after {timeout:g}s")
        except (asyncssh.Error, OSError):
            raise HostUnreachable("connection to the remote machine was lost")
        return CommandResult(_truncate(str(r.stdout or "")), _truncate(str(r.stderr or "")), r.exit_status)

    async def stream(self, command: str, timeout: float):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            proc = await self._conn.create_process(f"bash -lc {shlex.quote(command)}", stderr=asyncssh.STDOUT)
        except (asyncssh.Error, OSError):
            raise HostUnreachable("connection to the remote machine was lost")
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(4096), max(0.0, deadline - loop.time()))
                except asyncio.TimeoutError:
                    raise RemoteTimeout(f"command timed out after {timeout:g}s")
                if not chunk:
                    break
                yield ("output", chunk)
            await proc.wait_closed()
            yield ("exit", proc.exit_status)
        finally:
            proc.close()

    async def realpath(self, path: str) -> str:
        sftp = await self._get_sftp()
        with _sftp_errors(path):
            return await sftp.realpath(path)

    async def makedirs(self, path: str) -> None:
        sftp = await self._get_sftp()
        with _sftp_errors(path):
            await sftp.makedirs(path, exist_ok=True)

    async def write_file(self, path: str, data: bytes) -> None:
        sftp = await self._get_sftp()
        with _sftp_errors(path):
            async with sftp.open(path, "wb") as f:
                await f.write(data)

    async def read_file(self, path: str, max_bytes: int) -> bytes:
        sftp = await self._get_sftp()
        with _sftp_errors(path):
            attrs = await sftp.stat(path)
            if attrs.permissions is not None and stat.S_ISDIR(attrs.permissions):
                raise InvalidRequest(f"{path} is a directory")
            if (attrs.size or 0) > max_bytes:
                raise PayloadTooLarge(f"{path} is larger than {max_bytes // (1024 * 1024)} MB")
            async with sftp.open(path, "rb") as f:
                return await f.read()

    async def read_from(self, path: str, offset: int, max_bytes: int = 65536) -> bytes:
        sftp = await self._get_sftp()
        try:
            async with sftp.open(path, "rb") as f:
                await f.seek(offset)
                return await f.read(max_bytes)
        except asyncssh.SFTPNoSuchFile:
            return b""
        except asyncssh.SFTPError as e:
            raise HPCError(f"SFTP error on {path}: {e.reason}")

    async def listdir(self, path: str) -> list[FileInfo]:
        sftp = await self._get_sftp()
        with _sftp_errors(path):
            entries = await sftp.readdir(path)
        files = []
        for e in entries:
            name = str(e.filename)
            if name in (".", ".."):
                continue
            perms = e.attrs.permissions or 0
            mtime = e.attrs.mtime
            files.append(FileInfo(
                name=name, path=f"{path.rstrip('/')}/{name}", size=e.attrs.size or 0,
                is_dir=stat.S_ISDIR(perms),
                modified=datetime.fromtimestamp(mtime, timezone.utc) if mtime else None,
            ))
        return sorted(files, key=lambda f: (not f.is_dir, f.name))

    def is_alive(self) -> bool:
        return not self._client.lost and not (self._jump_client and self._jump_client.lost)

    async def close(self) -> None:
        for conn in (self._conn, self._jump):
            if conn is None:
                continue
            conn.close()
            try:
                await asyncio.wait_for(conn.wait_closed(), 5)
            except (asyncio.TimeoutError, asyncssh.Error, OSError):
                pass


class AsyncSSHBackend(HPCBackend):
    def __init__(self, settings: HPCSettings):
        self.settings = settings

    def _load_key(self, req: ConnectRequest):
        passphrase = req.passphrase.get_secret_value() if req.passphrase else None
        try:
            if req.private_key:
                return asyncssh.import_private_key(req.private_key.get_secret_value(), passphrase)
            if req.private_key_path:
                if not self.settings.allow_key_paths:
                    raise InvalidRequest("private_key_path is disabled on this server "
                                         "(set HPC_ALLOW_KEY_PATHS=true); upload the key instead")
                return asyncssh.read_private_key(os.path.expanduser(req.private_key_path), passphrase)
        except (asyncssh.KeyImportError, asyncssh.KeyEncryptionError, ValueError):
            raise InvalidRequest("could not load the private key (wrong format or passphrase?)")
        except OSError:
            raise InvalidRequest("could not read the private key file")
        return None

    async def _open(self, label: str, host: str, port: int, req: ConnectRequest, key, client: _Client,
                    tunnel=None) -> asyncssh.SSHClientConnection:
        """One hop. `label` names the hop in error messages ("jump host x" / "target y")."""
        s = self.settings
        if not s.strict_host_keys:
            known_hosts = None
            log.warning("HPC_STRICT_HOST_KEYS=false: not verifying host key for %s", host)
        else:
            known_hosts = s.known_hosts or ()  # () = asyncssh default, ~/.ssh/known_hosts
        try:
            return await asyncssh.connect(
                host, port,
                tunnel=tunnel,
                username=req.username,
                client_factory=lambda: client,
                client_keys=[key] if key else None,  # None: never use this server's own keys
                agent_path=None,
                config=None,
                known_hosts=known_hosts,
                keepalive_interval=s.keepalive_interval,
                keepalive_count_max=3,
                connect_timeout=s.connect_timeout,
                login_timeout=s.auth_timeout,
            )
        except asyncssh.PermissionDenied:
            raise AuthFailed(f"{label}: authentication failed (check username, password/key, or 2FA response)")
        except asyncssh.HostKeyNotVerifiable:
            raise HostUnreachable(f"{label}: host key is not trusted; add it to known_hosts "
                                  f"(run the manual ssh check once) or set HPC_KNOWN_HOSTS")
        except (asyncio.TimeoutError, TimeoutError):
            raise RemoteTimeout(f"{label}: timed out connecting on port {port}")
        except (asyncssh.Error, OSError) as e:
            raise HostUnreachable(f"{label}: could not connect on port {port} ({type(e).__name__})")

    async def connect(self, req: ConnectRequest, challenge: ChallengeHandler) -> HPCConnection:
        key = self._load_key(req)
        password = req.password.get_secret_value() if req.password else None
        jump = jump_client = None
        if req.jump_host:
            jump_client = _Client(password, challenge, req.jump_host)
            jump = await self._open(f"jump host {req.jump_host}", req.jump_host, req.jump_port, req, key,
                                    jump_client)
        client = _Client(password, challenge, req.host)
        label = f"target {req.host}" + (f" (via {req.jump_host})" if req.jump_host else "")
        try:
            conn = await self._open(label, req.host, req.port, req, key, client, tunnel=jump)
        except BaseException:
            if jump:
                jump.close()
            raise
        return AsyncSSHConnection(conn, client, jump, jump_client)


# ---------------------------------------------------------------------------
# Session manager (transport- and compute-agnostic)
# ---------------------------------------------------------------------------

@dataclass
class _Live:
    """In-process state for one session; never persisted."""

    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    pending: asyncio.Future | None = None
    task: asyncio.Task | None = None
    connection: HPCConnection | None = None
    error: HPCError | None = None


class SessionManager:
    """Opens connections, relays keyboard-interactive prompts (on any hop), reuses connections."""

    def __init__(self, backend: HPCBackend, compute: ComputeBackend, store: Store, settings: HPCSettings):
        self.backend = backend
        self.compute = compute
        self.store = store
        self.settings = settings
        self._live: dict[str, _Live] = {}

    def resolve(self, req: ConnectRequest) -> ConnectRequest:
        """Fill host/jump_host defaults from settings (jump_host "" means connect directly)."""
        host = (req.host or "").strip() or self.settings.target_host
        jump = self.settings.jump_host if req.jump_host is None else (req.jump_host.strip() or None)
        return req.model_copy(update={"host": host, "jump_host": jump})

    async def connect(self, req: ConnectRequest) -> ConnectResponse:
        req = self.resolve(req)
        session_id = secrets.token_urlsafe(18)
        record = SessionRecord(session_id=session_id, host=req.host, port=req.port,
                               username=req.username, jump_host=req.jump_host)
        await self.store.save_session(record)
        live = _Live()
        self._live[session_id] = live
        log.info("hpc connect start session=%s host=%s jump=%s user=%s",
                 session_id, req.host, req.jump_host, req.username)

        async def challenge(hop: str, instructions: str, prompts: list[AuthPrompt]) -> list[str]:
            fut = asyncio.get_running_loop().create_future()
            live.pending = fut
            record.status, record.hop = "awaiting_2fa", hop
            record.instructions, record.prompts = instructions or None, prompts
            await self.store.save_session(record)
            live.events.put_nowait("challenge")
            try:
                return await asyncio.wait_for(fut, self.settings.auth_timeout)
            finally:
                live.pending = None

        async def run() -> None:
            try:
                conn = await self.backend.connect(req, challenge)
                try:
                    record.base_dir = await self.compute.base_dir(conn, req.username)
                except BaseException:
                    await conn.close()
                    raise
            except asyncio.CancelledError:
                raise
            except HPCError as e:
                await self._fail(record, live, e)
                return
            except Exception:
                log.exception("hpc connect crashed session=%s", session_id)
                await self._fail(record, live, HostUnreachable("unexpected error while connecting"))
                return
            live.connection = conn
            record.status, record.connected_at = "connected", utcnow()
            record.prompts, record.instructions, record.hop = [], None, None
            await self.store.save_session(record)
            log.info("hpc connected session=%s", session_id)
            live.events.put_nowait("connected")

        live.task = asyncio.create_task(run())
        return await self._next_event(record, live)

    async def _fail(self, record: SessionRecord, live: _Live, error: HPCError) -> None:
        live.error = error
        record.status, record.error, record.prompts = "failed", error.detail, []
        await self.store.save_session(record)
        log.info("hpc connect failed session=%s status=%s", record.session_id, error.status_code)
        live.events.put_nowait("failed")

    async def _next_event(self, record: SessionRecord, live: _Live) -> ConnectResponse:
        try:
            event = await asyncio.wait_for(live.events.get(), self.settings.connect_timeout)
        except asyncio.TimeoutError:
            if live.task:
                live.task.cancel()
            await self._fail(record, live, RemoteTimeout("timed out waiting for the remote machine to respond"))
            event = "failed"
        if event == "failed":
            raise live.error or HostUnreachable("connection failed")
        record = await self._record(record.session_id)
        return ConnectResponse(session_id=record.session_id, status=record.status, hop=record.hop,
                               instructions=record.instructions, prompts=record.prompts)

    async def respond(self, session_id: str, responses: list[str]) -> ConnectResponse:
        record = await self._record(session_id)
        live = self._live.get(session_id)
        if live is None or live.pending is None or live.pending.done():
            raise SessionNotReady(f"session is '{record.status}', not waiting for a 2FA response")
        if len(responses) != len(record.prompts):
            raise InvalidRequest(f"expected {len(record.prompts)} response(s), got {len(responses)}")
        record.status = "connecting"
        await self.store.save_session(record)
        live.pending.set_result(responses)
        return await self._next_event(record, live)

    async def _record(self, session_id: str) -> SessionRecord:
        record = await self.store.get_session(session_id)
        if record is None:
            raise NotFound("session not found")
        return record

    async def status(self, session_id: str) -> SessionStatus:
        record = await self._record(session_id)
        live = self._live.get(session_id)
        if record.status == "connected" and (live is None or live.connection is None or not live.connection.is_alive()):
            record.status, record.error = "disconnected", "connection dropped; reconnect to continue"
            await self.store.save_session(record)
        return SessionStatus(
            session_id=record.session_id, host=record.host, port=record.port, username=record.username,
            jump_host=record.jump_host, status=record.status, mock=self.settings.mock,
            backend=self.compute.name, created_at=record.created_at, connected_at=record.connected_at,
            base_dir=record.base_dir, error=record.error, hop=record.hop, prompts=record.prompts,
        )

    async def list(self) -> list[SessionStatus]:
        return [await self.status(r.session_id) for r in await self.store.list_sessions()]

    async def connection(self, session_id: str) -> tuple[SessionRecord, HPCConnection]:
        """The live, reusable connection for a session (409 if it isn't connected)."""
        status = await self.status(session_id)
        live = self._live.get(session_id)
        if status.status != "connected" or live is None or live.connection is None:
            raise SessionNotReady(f"session is '{status.status}', not connected")
        return await self._record(session_id), live.connection

    async def context(self, record: SessionRecord) -> JobContext:
        jobs = await self.store.list_jobs(record.session_id)
        return JobContext(session_id=record.session_id, username=record.username, base_dir=record.base_dir,
                          our_pids={j.pid for j in jobs if j.pid})

    async def disconnect(self, session_id: str) -> None:
        await self._record(session_id)
        live = self._live.pop(session_id, None)
        if live:
            if live.task and not live.task.done():
                live.task.cancel()
            if live.connection:
                await live.connection.close()
        await self.store.delete_session(session_id)
        log.info("hpc disconnected session=%s", session_id)

    async def close_all(self) -> None:
        for session_id in list(self._live):
            await self.disconnect(session_id)
