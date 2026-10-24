"""SLURM compute backend: sbatch generation, squeue/sacct parsing, submit/status/cancel."""

import asyncio
import re
import secrets
import shlex
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .backend import (
    ComputeBackend, Forbidden, HPCConnection, InvalidRequest, JobContext, JobRecordData, NotFound,
    SlurmError, job_command,
)
from .config import HPCSettings
from .models import JobSpec, JobState, JobStatus, JobSubmitResponse, JobTask

SLURM_TIMEOUT = 60.0
SLURM_ALLOWED = {"sbatch", "squeue", "sacct", "scancel", "ls", "cat", "mkdir", "module"}

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    autoescape=False,  # shell script, not HTML; values are validated or shell-quoted
)
_env.filters["shquote"] = lambda v: shlex.quote(str(v))

JOB_ID_RE = re.compile(r"^\d+(_\d+)?$")

_STATE_MAP = {
    "PENDING": JobState.PENDING, "CONFIGURING": JobState.PENDING, "REQUEUED": JobState.PENDING,
    "RESV_DEL_HOLD": JobState.PENDING, "REQUEUE_HOLD": JobState.PENDING, "SUSPENDED": JobState.PENDING,
    "RUNNING": JobState.RUNNING, "COMPLETING": JobState.RUNNING, "STAGE_OUT": JobState.RUNNING,
    "RESIZING": JobState.RUNNING, "SIGNALING": JobState.RUNNING,
    "COMPLETED": JobState.COMPLETED,
    "CANCELLED": JobState.CANCELLED, "REVOKED": JobState.CANCELLED, "PREEMPTED": JobState.CANCELLED,
    "FAILED": JobState.FAILED, "TIMEOUT": JobState.FAILED, "NODE_FAIL": JobState.FAILED,
    "OUT_OF_MEMORY": JobState.FAILED, "BOOT_FAIL": JobState.FAILED, "DEADLINE": JobState.FAILED,
}
TERMINAL_STATES = {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED}


def render_sbatch(spec: JobSpec, work_dir: str, project_dir: str) -> str:
    """Render templates/job.sbatch.j2 for a validated spec."""
    if re.search(r"\s", work_dir):
        raise InvalidRequest("remote working directory must not contain whitespace")
    param_values: dict[str, list] = {}
    if spec.parameters:
        for name in spec.parameters[0]:
            param_values[name] = [variation[name] for variation in spec.parameters]
    return _env.get_template("job.sbatch.j2").render(
        spec=spec,
        command=job_command(spec),
        work_dir=work_dir,
        project_dir=project_dir,
        array_size=len(spec.parameters) if spec.parameters else None,
        param_values=param_values,
    )


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_RE.match(job_id):
        raise InvalidRequest("job_id must look like 12345 or 12345_6")
    return job_id


def sbatch_command(script_path: str) -> str:
    return f"sbatch --parsable {shlex.quote(script_path)}"


def squeue_command(job_id: str) -> str:
    return f"squeue -h -r -j {validate_job_id(job_id)} -o '%i|%T|%M|%r'"


def sacct_command(job_id: str) -> str:
    return f"sacct -j {validate_job_id(job_id)} -X -n -P -o JobID,State,Elapsed,ExitCode"


def scancel_command(job_id: str) -> str:
    return f"scancel {validate_job_id(job_id)}"


def parse_sbatch_output(stdout: str, stderr: str, exit_code: int | None) -> str:
    """`sbatch --parsable` prints "<jobid>" or "<jobid>;<cluster>"."""
    if exit_code != 0:
        raise SlurmError(f"sbatch failed: {(stderr or stdout).strip() or 'unknown error'}")
    m = re.search(r"^(\d+)(;\S+)?\s*$", stdout.strip(), re.MULTILINE)
    if not m:
        raise SlurmError(f"could not parse job id from sbatch output: {stdout.strip()!r}")
    return m.group(1)


def normalize_state(raw: str) -> JobState:
    # sacct prints e.g. "CANCELLED by 12345"; squeue prints long names.
    word = raw.strip().split(" ")[0].rstrip("+").upper() if raw.strip() else ""
    return _STATE_MAP.get(word, JobState.UNKNOWN)


def _exit_code(value: str) -> int | None:
    m = re.match(r"^(\d+):(\d+)$", value.strip())
    if not m:
        return None
    code, signal = int(m.group(1)), int(m.group(2))
    return code if code or not signal else 128 + signal


def parse_squeue(stdout: str) -> list[JobTask]:
    tasks = []
    for line in stdout.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 2 or not parts[0]:
            continue
        reason = parts[3] if len(parts) > 3 and parts[3] not in ("None", "") else None
        tasks.append(JobTask(task_id=parts[0], state=normalize_state(parts[1]), raw_state=parts[1],
                             elapsed=parts[2] if len(parts) > 2 else None, reason=reason))
    return tasks


def parse_sacct(stdout: str) -> list[JobTask]:
    tasks = []
    for line in stdout.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 4 or not parts[0]:
            continue
        tasks.append(JobTask(task_id=parts[0], state=normalize_state(parts[1]), raw_state=parts[1],
                             elapsed=parts[2] or None, exit_code=_exit_code(parts[3])))
    return tasks


def merge_tasks(squeue: list[JobTask], sacct: list[JobTask]) -> list[JobTask]:
    """squeue is live (wins on conflicts); sacct adds finished tasks and exit codes."""
    merged = {t.task_id: t for t in sacct}
    for t in squeue:
        old = merged.get(t.task_id)
        merged[t.task_id] = t.model_copy(update={"exit_code": old.exit_code if old else None})
    # Drop the "123_[0-3]" placeholder once individual tasks are visible.
    if any("[" not in k for k in merged):
        merged = {k: v for k, v in merged.items() if "[" not in k}
    return sorted(merged.values(), key=lambda t: _sort_key(t.task_id))


def _sort_key(task_id: str) -> tuple[int, int]:
    main, _, sub = task_id.partition("_")
    return (int(main) if main.isdigit() else 0, int(sub) if sub.isdigit() else -1)


def aggregate_status(job_id: str, tasks: list[JobTask]) -> JobStatus:
    if not tasks:
        raise NotFound(f"job {job_id} not found in squeue or sacct")
    states = {t.state for t in tasks}
    if JobState.RUNNING in states:
        state = JobState.RUNNING
    elif JobState.PENDING in states:
        state = JobState.PENDING
    elif JobState.FAILED in states:
        state = JobState.FAILED
    elif JobState.CANCELLED in states:
        state = JobState.CANCELLED
    elif states == {JobState.COMPLETED}:
        state = JobState.COMPLETED
    else:
        state = JobState.UNKNOWN
    codes = [t.exit_code for t in tasks if t.exit_code is not None]
    exit_code = next((c for c in codes if c), 0 if codes and len(codes) == len(tasks) else None)
    return JobStatus(
        job_id=job_id,
        state=state,
        elapsed=max((t.elapsed for t in tasks if t.elapsed), key=_elapsed_seconds, default=None),
        exit_code=exit_code if state in TERMINAL_STATES else None,
        tasks=tasks,
    )


def _elapsed_seconds(value: str) -> int:
    """Parse SLURM durations like 1-02:03:04, 02:03:04, 03:04."""
    if not value:
        return -1
    days, _, rest = value.rpartition("-")
    parts = [int(p) for p in rest.split(":") if p.isdigit()]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3:]
    return (int(days) if days.isdigit() else 0) * 86400 + h * 3600 + m * 60 + s


def new_work_dir(project_dir: str, job_name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{project_dir}/jobs/{job_name}-{stamp}-{secrets.token_hex(2)}"


class SlurmBackend(ComputeBackend):
    """Cluster login node with SLURM (e.g. Roar Collab). Parameter sweeps become job arrays."""

    name = "slurm"

    def __init__(self, settings: HPCSettings):
        self.settings = settings

    async def base_dir(self, conn: HPCConnection, username: str) -> str:
        base = self.settings.remote_base_dir
        if not base.startswith("/"):
            base = f"{(await conn.realpath('.')).rstrip('/')}/{base}"
        return base.rstrip("/")

    def check_command(self, argv: list[str], ctx: JobContext) -> list[str]:
        if argv[0] not in SLURM_ALLOWED:
            raise Forbidden(f"'{argv[0]}' is not allowed; allowed: {', '.join(sorted(SLURM_ALLOWED))}")
        return argv

    async def submit_job(self, conn: HPCConnection, ctx: JobContext, spec: JobSpec):
        project_dir = ctx.project_dir(spec.project)
        work_dir = new_work_dir(project_dir, spec.job_name)
        script = render_sbatch(spec, work_dir, project_dir)
        script_path = f"{work_dir}/job.sbatch"
        array_size = len(spec.parameters) if spec.parameters else None
        warnings = [f"'{f}' is ignored on the slurm backend" for f in ("venv", "force")
                    if getattr(spec, f)]
        response = JobSubmitResponse(job_id=None, submitted=False, backend=self.name, script=script,
                                     script_path=script_path, work_dir=work_dir,
                                     array_size=array_size, warnings=warnings)
        if spec.dry_run:
            return response, None

        await conn.makedirs(work_dir)
        if spec.script is not None:
            await conn.write_file(f"{work_dir}/{spec.script_filename}", spec.script.encode())
        await conn.write_file(script_path, script.encode())
        result = await conn.run(sbatch_command(script_path), timeout=SLURM_TIMEOUT)
        job_id = parse_sbatch_output(result.stdout, result.stderr, result.exit_code)
        response.job_id, response.submitted = job_id, True
        return response, JobRecordData(job_id=job_id, work_dir=work_dir, script_path=script_path,
                                       array_size=array_size)

    async def job_status(self, conn: HPCConnection, job_id: str, record) -> JobStatus:
        validate_job_id(job_id)
        squeue, sacct = await asyncio.gather(
            conn.run(squeue_command(job_id), timeout=SLURM_TIMEOUT),
            conn.run(sacct_command(job_id), timeout=SLURM_TIMEOUT),
        )
        # squeue exits non-zero once a job leaves the queue; sacct may be disabled. Either alone is fine.
        tasks = merge_tasks(parse_squeue(squeue.stdout) if squeue.exit_code == 0 else [],
                            parse_sacct(sacct.stdout) if sacct.exit_code == 0 else [])
        status = aggregate_status(job_id, tasks)
        status.work_dir = record.work_dir if record else None
        return status

    async def cancel(self, conn: HPCConnection, job_id: str, record) -> None:
        result = await conn.run(scancel_command(job_id), timeout=SLURM_TIMEOUT)
        if result.exit_code != 0:
            raise SlurmError(f"scancel failed: {(result.stderr or result.stdout).strip() or 'unknown error'}")

    def log_path(self, record, task: int) -> str:
        """Must match the --output pattern in templates/job.sbatch.j2."""
        if record.array_size is None:
            return f"{record.work_dir}/slurm-{record.job_id}.out"
        return f"{record.work_dir}/slurm-{record.job_id}_{task}.out"
