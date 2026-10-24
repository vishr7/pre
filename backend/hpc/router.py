"""PRE HPC router. Mount into the main app with:

    from hpc.router import router as hpc_router, shutdown_hpc
    app.include_router(hpc_router)
    # and call `await shutdown_hpc()` on app shutdown to close SSH connections
"""

import asyncio
import codecs
import json
import mimetypes
import posixpath
import re
import shlex
from functools import lru_cache

from fastapi import APIRouter, Depends, Path, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from .backend import ComputeBackend, HPCConnection, HPCError, InvalidRequest, NotFound, PayloadTooLarge
from .config import get_hpc_settings
from .mock_backend import MockBackend
from .models import (
    JOB_ID_RE, NAME_RE, ConnectRequest, ConnectResponse, EnvSetupRequest, ExecRequest, ExecResponse,
    FileListResponse, GPUList, JobSpec, JobStatus, JobSubmitResponse, JobSummary, RespondRequest,
    ResultFile, SessionStatus, UploadResponse,
)
from .slurm import TERMINAL_STATES, SlurmBackend
from .ssh_client import AsyncSSHBackend, SessionManager, parse_user_command, safe_relpath
from .store import InMemoryStore, JobRecord, SessionRecord
from .workstation import WorkstationBackend, env_setup_script, venv_dir

router = APIRouter(prefix="/hpc", tags=["hpc"])

ProjectName = Path(pattern=NAME_RE, description="Per-project working directory name")


@lru_cache(maxsize=1)
def get_manager() -> SessionManager:
    settings = get_hpc_settings()
    transport = MockBackend(settings) if settings.mock else AsyncSSHBackend(settings)
    compute: ComputeBackend = (WorkstationBackend(settings) if settings.compute_backend == "workstation"
                               else SlurmBackend(settings))
    return SessionManager(transport, compute, InMemoryStore(), settings)


async def shutdown_hpc() -> None:
    if get_manager.cache_info().currsize:
        await get_manager().close_all()


Manager = Depends(get_manager)


# ---------------------------------------------------------------------------
# connection management
# ---------------------------------------------------------------------------

@router.get("/health")
def health(manager: SessionManager = Manager):
    s = manager.settings
    return {"status": "ok", "mock": s.mock, "backend": manager.compute.name,
            "target_host": s.target_host, "jump_host": s.jump_host}


@router.post("/connect", response_model=ConnectResponse)
async def connect(req: ConnectRequest, manager: SessionManager = Manager):
    """Start a session (through the jump host if configured). Returns status "connected",
    or "awaiting_2fa" with the prompts and the `hop` asking them."""
    return await manager.connect(req)


@router.post("/connect/{session_id}/respond", response_model=ConnectResponse)
async def respond(session_id: str, body: RespondRequest, manager: SessionManager = Manager):
    """Answer the pending keyboard-interactive prompts (e.g. a Duo passcode, or "1" for push).
    May return another "awaiting_2fa" if the next hop asks too."""
    return await manager.respond(session_id, [r.get_secret_value() for r in body.responses])


@router.get("/sessions", response_model=list[SessionStatus])
async def list_sessions(manager: SessionManager = Manager):
    return await manager.list()


@router.get("/sessions/{session_id}/status", response_model=SessionStatus)
async def session_status(session_id: str, manager: SessionManager = Manager):
    return await manager.status(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
async def disconnect(session_id: str, manager: SessionManager = Manager):
    await manager.disconnect(session_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# remote commands, GPUs, environments
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/exec", response_model=ExecResponse)
async def exec_command(session_id: str, req: ExecRequest, manager: SessionManager = Manager):
    """Run one allowlisted command. The allowlist depends on the compute backend (see README)."""
    argv = parse_user_command(req.command)
    record, conn = await manager.connection(session_id)
    command = shlex.join(manager.compute.check_command(argv, await manager.context(record)))
    result = await conn.run(command, timeout=min(req.timeout, manager.settings.exec_max_timeout))
    return ExecResponse(command=command, stdout=result.stdout, stderr=result.stderr,
                        exit_code=result.exit_code)


@router.get("/sessions/{session_id}/gpus", response_model=GPUList)
async def gpus(session_id: str, manager: SessionManager = Manager):
    """Per-GPU usage from nvidia-smi, with busy/free based on GPU_BUSY_* thresholds."""
    record, conn = await manager.connection(session_id)
    return await manager.compute.gpus(conn, await manager.context(record))


@router.post("/sessions/{session_id}/env")
async def setup_env(session_id: str, req: EnvSetupRequest, manager: SessionManager = Manager):
    """Create <project>/venvs/<name> (optionally with a pyenv Python) and pip install requirements.

    Streams NDJSON: {"type": "output", "data": ...} lines, then {"type": "done", "exit_code", "venv"}
    (or {"type": "error", ...}).
    """
    record, conn = await manager.connection(session_id)
    project_dir = f"{record.base_dir}/{req.project}"
    venv = venv_dir(project_dir, req.name)
    script = env_setup_script(project_dir, req.name, req.python_version, req.requirements)
    await conn.makedirs(project_dir)

    async def events():
        try:
            async for kind, value in conn.stream(script, manager.settings.env_timeout):
                if kind == "output":
                    yield json.dumps({"type": "output", "data": value}) + "\n"
                else:
                    yield json.dumps({"type": "done", "exit_code": value, "venv": venv}) + "\n"
        except HPCError as e:
            yield json.dumps({"type": "error", "status": e.status_code, "detail": e.detail}) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# files (SFTP), scoped to <base_dir>/<project>/
# ---------------------------------------------------------------------------

def _project_dir(record: SessionRecord, project: str) -> str:
    return f"{record.base_dir}/{project}"


# Fixed types for common result files; mimetypes alone is OS-dependent (Windows maps .csv to Excel).
MEDIA_TYPES = {".csv": "text/csv", ".json": "application/json", ".png": "image/png",
               ".svg": "image/svg+xml", ".txt": "text/plain", ".out": "text/plain", ".log": "text/plain",
               ".py": "text/x-python", ".sbatch": "text/plain", ".sh": "text/plain"}


async def _download(conn: HPCConnection, path: str, max_bytes: int) -> Response:
    data = await conn.read_file(path, max_bytes)
    name = posixpath.basename(path)
    media_type = (MEDIA_TYPES.get(posixpath.splitext(name)[1].lower())
                  or mimetypes.guess_type(name)[0] or "application/octet-stream")
    return Response(content=data, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.put("/sessions/{session_id}/projects/{project}/files/{path:path}", response_model=UploadResponse)
async def upload_file(session_id: str, path: str, request: Request,
                      project: str = ProjectName, manager: SessionManager = Manager):
    """Upload the raw request body, e.g. `curl -T train.py .../files/train.py`."""
    rel = safe_relpath(path)
    if not rel:
        raise InvalidRequest("a file path is required")
    data = await request.body()
    if len(data) > manager.settings.max_download_bytes:
        raise PayloadTooLarge("upload is too large")
    record, conn = await manager.connection(session_id)
    full = f"{_project_dir(record, project)}/{rel}"
    await conn.makedirs(posixpath.dirname(full))
    await conn.write_file(full, data)
    return UploadResponse(path=full, size=len(data))


@router.get("/sessions/{session_id}/projects/{project}/files", response_model=FileListResponse)
async def list_files(session_id: str, project: str = ProjectName, path: str = "",
                     manager: SessionManager = Manager):
    record, conn = await manager.connection(session_id)
    root = _project_dir(record, project)
    rel = safe_relpath(path)
    if not rel:
        await conn.makedirs(root)  # a brand-new project lists as empty, not 404
    full = f"{root}/{rel}" if rel else root
    return FileListResponse(path=full, files=await conn.listdir(full))


@router.get("/sessions/{session_id}/projects/{project}/files/{path:path}")
async def download_file(session_id: str, path: str, project: str = ProjectName,
                        manager: SessionManager = Manager):
    rel = safe_relpath(path)
    if not rel:
        raise InvalidRequest("a file path is required")
    record, conn = await manager.connection(session_id)
    return await _download(conn, f"{_project_dir(record, project)}/{rel}", manager.settings.max_download_bytes)


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

def _job_id(job_id: str) -> str:
    if not re.match(JOB_ID_RE, job_id):
        raise InvalidRequest("invalid job id")
    return job_id


@router.post("/sessions/{session_id}/jobs", response_model=JobSubmitResponse)
async def submit_job(session_id: str, spec: JobSpec, manager: SessionManager = Manager):
    """Generate the job script (returned for review) and launch it unless dry_run is set.

    workstation: background process on one GPU (409 with GPU details if it's busy, unless
    force=true); `parameters` run sequentially, each in run_<i>/.
    slurm: sbatch; `parameters` become a job array.
    Each run sees its parameter values as environment variables (e.g. $LR).
    """
    record, conn = await manager.connection(session_id)
    response, data = await manager.compute.submit_job(conn, await manager.context(record), spec)
    if data is not None:
        await manager.store.save_job(JobRecord(
            job_id=data.job_id, session_id=session_id, backend=manager.compute.name, job_name=spec.job_name,
            project=spec.project, work_dir=data.work_dir, script_path=data.script_path,
            array_size=data.array_size, pid=data.pid, gpu=data.gpu,
        ))
    return response


@router.get("/sessions/{session_id}/jobs", response_model=list[JobSummary])
async def list_jobs(session_id: str, manager: SessionManager = Manager):
    """Jobs submitted through this session."""
    await manager.status(session_id)  # 404 for unknown sessions
    return [JobSummary(job_id=j.job_id, job_name=j.job_name, project=j.project, backend=j.backend,
                       work_dir=j.work_dir, array_size=j.array_size, pid=j.pid, gpu=j.gpu,
                       submitted_at=j.submitted_at)
            for j in await manager.store.list_jobs(session_id)]


async def _job(manager: SessionManager, session_id: str, job_id: str) -> JobRecord:
    job = await manager.store.get_job(session_id, _job_id(job_id))
    if job is None:
        raise NotFound(f"job {job_id} was not submitted through this session")
    return job


@router.get("/sessions/{session_id}/jobs/{job_id}", response_model=JobStatus)
async def job_status(session_id: str, job_id: str, manager: SessionManager = Manager):
    """On slurm this also works for job IDs PRE didn't submit."""
    _, conn = await manager.connection(session_id)
    record = await manager.store.get_job(session_id, _job_id(job_id))
    return await manager.compute.job_status(conn, job_id, record)


@router.post("/sessions/{session_id}/jobs/{job_id}/cancel", response_model=JobStatus)
async def cancel_job(session_id: str, job_id: str, manager: SessionManager = Manager):
    """workstation: TERM (then KILL) the job's whole process group. slurm: scancel."""
    _, conn = await manager.connection(session_id)
    record = await manager.store.get_job(session_id, _job_id(job_id))
    await manager.compute.cancel(conn, job_id, record)
    return await manager.compute.job_status(conn, job_id, record)


@router.websocket("/sessions/{session_id}/jobs/{job_id}/stream")
async def stream_job(ws: WebSocket, session_id: str, job_id: str, task: int = Query(0, ge=0),
                     manager: SessionManager = Manager):
    """Push {"type": "status"|"log"|"done"|"error", ...} messages until the job finishes.

    `task` picks which SLURM array task's log to tail (default 0); a workstation sweep
    has a single log covering every run.
    """
    await ws.accept()
    try:
        try:
            _, conn = await manager.connection(session_id)
            job = await manager.store.get_job(session_id, _job_id(job_id))
            log_path = manager.compute.log_path(job, task) if job else None
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            offset, last = 0, None
            while True:
                status = await manager.compute.job_status(conn, job_id, job)
                payload = status.model_dump(mode="json")
                if payload != last:
                    await ws.send_json({"type": "status", **payload})
                    last = payload
                while log_path:
                    chunk = await conn.read_from(log_path, offset)
                    if not chunk:
                        break
                    offset += len(chunk)
                    await ws.send_json({"type": "log", "data": decoder.decode(chunk)})
                if status.state in TERMINAL_STATES:
                    await ws.send_json({"type": "done", "state": status.state.value,
                                        "exit_code": status.exit_code})
                    break
                await asyncio.sleep(manager.settings.poll_interval)
        except HPCError as e:
            await ws.send_json({"type": "error", "status": e.status_code, "detail": e.detail})
        await ws.close()
    except (WebSocketDisconnect, RuntimeError):
        pass  # client went away


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/jobs/{job_id}/results", response_model=list[ResultFile])
async def list_results(session_id: str, job_id: str,
                       ext: str | None = Query(None, description="Comma-separated filter, e.g. csv,json,png"),
                       manager: SessionManager = Manager):
    """Files in the job's directory and one level of subdirectories (e.g. run_<i>/)."""
    _, conn = await manager.connection(session_id)
    job = await _job(manager, session_id, job_id)
    wanted = {e.strip().lower().lstrip(".") for e in ext.split(",")} if ext else None
    out: list[ResultFile] = []
    pending = [(job.work_dir, 0)]
    while pending:
        directory, depth = pending.pop(0)
        for f in await conn.listdir(directory):
            if f.is_dir:
                if depth < 1:
                    pending.append((f.path, depth + 1))
                continue
            kind = posixpath.splitext(f.name)[1].lower().lstrip(".")
            if wanted is None or kind in wanted:
                out.append(ResultFile(**f.model_dump(), kind=kind))
    return out


@router.get("/sessions/{session_id}/jobs/{job_id}/results/{path:path}")
async def download_result(session_id: str, job_id: str, path: str, manager: SessionManager = Manager):
    rel = safe_relpath(path)
    if not rel:
        raise InvalidRequest("a file path is required")
    _, conn = await manager.connection(session_id)
    job = await _job(manager, session_id, job_id)
    return await _download(conn, f"{job.work_dir}/{rel}", manager.settings.max_download_bytes)
