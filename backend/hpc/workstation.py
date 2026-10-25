"""Workstation compute backend (Penn State Nittany AI Compute): no scheduler, shared GPUs.

Jobs run as detached background processes (`setsid nohup bash run.sh`). The wrapper
writes `pid`, `child_pid`, `output.log` and finally `exit_code` into the job directory;
status comes from `kill -0 <pid>` plus those files. Parameter sweeps run sequentially
on one GPU, each variation in its own run_<i>/ folder.
"""

import asyncio
import json
import posixpath
import re
import shlex
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .backend import (
    ComputeBackend, Forbidden, GPUBusy, HostUnreachable, HPCConnection, HPCError, InvalidRequest,
    JobContext, JobRecordData, NotFound, job_command,
)
from .config import HPCSettings
from .models import GPUInfo, GPUList, GPUProcess, JobSpec, JobState, JobStatus, JobSubmitResponse, JobTask
from .slurm import new_work_dir

NVSMI_GPUS = ("nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu "
              "--format=csv,noheader,nounits")
NVSMI_APPS = "nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader"
CMD_TIMEOUT = 30.0
START_GRACE_SECONDS = 30  # how long a job may lack a pid file before it counts as failed

_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), undefined=StrictUndefined,
                   trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True, autoescape=False)
_env.filters["shquote"] = lambda v: shlex.quote(str(v))

# SLURM-only JobSpec fields; warn when they're set to anything but the default.
SLURM_ONLY = ("partition", "account", "modules", "conda_env", "max_concurrent", "nodes", "ntasks",
              "cpus_per_task", "memory", "gpus")


# ---------------------------------------------------------------------------
# nvidia-smi
# ---------------------------------------------------------------------------

def _num(value: str) -> int | None:
    """'30215' / '30215 MiB' / '[N/A]' -> int or None."""
    m = re.search(r"-?\d+(\.\d+)?", value)
    return int(float(m.group())) if m else None


def parse_gpus(text: str) -> list[dict]:
    """Parse `nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu`."""
    gpus = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        # A name could contain commas; the last three fields are always numeric.
        gpus.append({"index": int(parts[0]), "uuid": parts[1] or None, "name": ", ".join(parts[2:-3]),
                     "memory_used_mb": _num(parts[-3]), "memory_total_mb": _num(parts[-2]),
                     "utilization_percent": _num(parts[-1])})
    return gpus


def parse_compute_apps(text: str) -> list[tuple[int | None, str, int | None]]:
    """Parse `nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory` -> (pid, uuid, MiB)."""
    apps = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or not parts[1].startswith("GPU-"):
            continue  # e.g. "No running processes found"
        apps.append((_num(parts[0]), parts[1], _num(parts[2])))
    return apps


def build_gpu_list(gpu_text: str, apps_text: str, util_threshold: float, mem_threshold: float,
                   our_pids: set[int]) -> list[GPUInfo]:
    apps = parse_compute_apps(apps_text)
    out = []
    for g in parse_gpus(gpu_text):
        reasons = []
        if g["utilization_percent"] is not None and g["utilization_percent"] > util_threshold:
            reasons.append(f"utilization {g['utilization_percent']}% > {util_threshold:g}%")
        if g["memory_used_mb"] is not None and g["memory_used_mb"] > mem_threshold:
            reasons.append(f"memory used {g['memory_used_mb']} MB > {mem_threshold:g} MB")
        procs = [GPUProcess(pid=pid, used_memory_mb=mem, ours=pid in our_pids)
                 for pid, uuid, mem in apps if uuid == g["uuid"]]
        out.append(GPUInfo(**g, busy=bool(reasons), busy_reasons=reasons, processes=procs))
    return out


def pick_gpu(gpus: list[GPUInfo], requested: int | str) -> GPUInfo:
    """A specific index, or for "auto" the least-loaded free GPU (least-loaded busy one if none free)."""
    if not gpus:
        raise InvalidRequest('no GPUs found on this machine; use "gpu": "none" for a CPU job')
    if isinstance(requested, int):
        for g in gpus:
            if g.index == requested:
                return g
        raise InvalidRequest(f"GPU {requested} does not exist (available: {', '.join(str(g.index) for g in gpus)})")
    # Unknown ([N/A]) stats sort after known-idle GPUs.
    return min(gpus, key=lambda g: (g.busy, 101 if g.utilization_percent is None else g.utilization_percent,
                                    float("inf") if g.memory_used_mb is None else g.memory_used_mb))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def launch_command(script_path: str, log_path: str) -> str:
    """Detach from the SSH session: new session (process group) + ignore SIGHUP."""
    return (f"setsid nohup bash {shlex.quote(script_path)} > {shlex.quote(log_path)} 2>&1 "
            f"< /dev/null & echo $!")


def venv_dir(project_dir: str, name: str) -> str:
    return f"{project_dir}/venvs/{name}"


def env_setup_script(project_dir: str, name: str, python_version: str | None, requirements: list[str]) -> str:
    """Shell script that creates <project>/venvs/<name> and pip installs requirements.

    The first line is a machine-readable marker (also used by the mock backend).
    """
    venv = venv_dir(project_dir, name)
    q = shlex.quote
    meta = json.dumps({"venv": venv, "python_version": python_version, "requirements": requirements})
    lines = [f"# PRE-ENV {meta}", "set -eo pipefail", f"mkdir -p {q(project_dir + '/venvs')}"]
    if python_version:
        lines += [
            'PYENV="$(command -v pyenv || echo "$HOME/.pyenv/bin/pyenv")"',
            f'echo "[PRE] pyenv install -s {python_version}"',
            f'"$PYENV" install -s {q(python_version)}',
            f'PY="$("$PYENV" root)/versions/{python_version}/bin/python"',
        ]
    else:
        lines.append('PY="$(command -v python3)"')
    lines += [
        'echo "[PRE] creating venv with $("$PY" --version 2>&1)"',
        f'"$PY" -m venv {q(venv)}',
        f"{q(venv + '/bin/python')} -m pip install --upgrade pip",
    ]
    if requirements:
        lines.append(f"{q(venv + '/bin/python')} -m pip install " + " ".join(q(r) for r in requirements))
    lines.append(f'echo "[PRE] environment ready: {venv}"')
    return "\n".join(lines) + "\n"


def _elapsed(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def _fields(text: str | None) -> list[int]:
    return [int(x) for x in (text or "").split() if x.lstrip("-").isdigit()]


async def _read_small(conn: HPCConnection, path: str) -> str | None:
    data = await conn.read_from(path, 0, 4096)
    return data.decode(errors="replace").strip() or None


# ---------------------------------------------------------------------------
# exec allowlist
# ---------------------------------------------------------------------------

FREE_COMMANDS = {"nvidia-smi", "ps", "pyenv"}
PATH_COMMANDS = {"ls": set(), "cat": set(), "tail": {"-n", "-c", "--lines", "--bytes"}, "mkdir": {"-m", "--mode"}}
VENV_BIN_RE = re.compile(r"/venvs/[A-Za-z0-9][A-Za-z0-9_.-]*/bin/(python3?(\.\d+)?|pip3?)$")
ALLOWED_HELP = "nvidia-smi, ps, kill (PRE job PIDs), ls, cat, tail, mkdir, pyenv, <project>/venvs/<name>/bin/python|pip"


def _inside(path: str, base: str) -> str:
    p = posixpath.normpath(path if path.startswith("/") else f"{base}/{path}")
    if p != base and not p.startswith(base + "/"):
        raise Forbidden(f"path {path!r} is outside {base}")
    return p


def _check_kill(argv: list[str], ctx: JobContext) -> list[str]:
    targets, after_dd, skip = [], False, False
    for a in argv[1:]:
        if skip:
            skip = False
            continue
        if a == "--":
            after_dd = True
            continue
        if not after_dd and a == "-s":
            skip = True
            continue
        if not after_dd and a.startswith("-"):
            sig = a[1:].upper()
            if sig.isalpha() or (sig.isdigit() and int(sig) <= 64):
                continue  # a signal, e.g. -TERM / -9
        number = a[1:] if a.startswith("-") else a
        if not number.isdigit():
            raise Forbidden(f"kill: invalid target {a!r}")
        targets.append(int(number))
    if not targets:
        raise InvalidRequest("kill needs at least one PID")
    others = [t for t in targets if t not in ctx.our_pids]
    if others:
        raise Forbidden(f"kill is limited to PIDs of PRE jobs in this session "
                        f"({', '.join(map(str, sorted(ctx.our_pids))) or 'none yet'}); refused {others}")
    return argv


# ---------------------------------------------------------------------------
# backend
# ---------------------------------------------------------------------------

class WorkstationBackend(ComputeBackend):
    name = "workstation"

    def __init__(self, settings: HPCSettings):
        self.settings = settings

    async def base_dir(self, conn: HPCConnection, username: str) -> str:
        base = f"{self.settings.base_dir}/{username}"
        try:
            await conn.makedirs(base)
        except HPCError as e:
            raise type(e)(f"could not create {base} ({e.detail}); "
                          f"check that {self.settings.base_dir} exists and is writable")
        return base

    def check_command(self, argv: list[str], ctx: JobContext) -> list[str]:
        cmd, base = argv[0], ctx.base_dir
        if cmd in FREE_COMMANDS:
            if cmd == "nvidia-smi" and any(a in ("-f", "--filename") or a.startswith("--filename=") for a in argv):
                raise Forbidden("nvidia-smi may not write files")
            return argv
        if cmd == "kill":
            return _check_kill(argv, ctx)
        if cmd in PATH_COMMANDS:
            out, takes_value = [cmd], False
            for a in argv[1:]:
                if takes_value or a.startswith("-"):
                    out.append(a)
                    takes_value = not takes_value and a in PATH_COMMANDS[cmd]
                    continue
                out.append(_inside(a, base))
            if len(out) == 1 or all(a.startswith("-") for a in out[1:]):
                out.append(base)  # default to the user's base dir, not $HOME
            return out
        if "/" in cmd:
            path = _inside(cmd, base)
            if VENV_BIN_RE.search(path):
                return [path, *argv[1:]]
        raise Forbidden(f"'{cmd}' is not allowed; allowed: {ALLOWED_HELP}")

    async def gpus(self, conn: HPCConnection, ctx: JobContext) -> GPUList:
        gpu_r, apps_r = await asyncio.gather(conn.run(NVSMI_GPUS, CMD_TIMEOUT), conn.run(NVSMI_APPS, CMD_TIMEOUT))
        if gpu_r.exit_code != 0:
            raise HostUnreachable(f"nvidia-smi failed: {(gpu_r.stderr or gpu_r.stdout).strip() or 'no output'}")
        s = self.settings
        gpus = build_gpu_list(gpu_r.stdout, apps_r.stdout if apps_r.exit_code == 0 else "",
                              s.gpu_busy_util_percent, s.gpu_busy_memory_mb, ctx.our_pids)
        return GPUList(gpus=gpus, busy_util_percent=s.gpu_busy_util_percent, busy_memory_mb=s.gpu_busy_memory_mb)

    async def submit_job(self, conn: HPCConnection, ctx: JobContext, spec: JobSpec):
        project_dir = ctx.project_dir(spec.project)
        work_dir = new_work_dir(project_dir, spec.job_name)
        job_id = posixpath.basename(work_dir)
        log_path = f"{work_dir}/output.log"
        defaults = JobSpec.model_fields
        warnings = [f"'{f}' is ignored on the workstation backend" for f in SLURM_ONLY
                    if getattr(spec, f) != defaults[f].get_default(call_default_factory=True)]

        gpu_index = None
        if spec.gpu != "none":
            gpu_list = await self.gpus(conn, ctx)
            chosen = pick_gpu(gpu_list.gpus, spec.gpu)
            if chosen.busy:
                why = f"GPU {chosen.index} ({chosen.name}) is busy: {'; '.join(chosen.busy_reasons)}"
                if spec.force:
                    warnings.append(f"{why}; launching anyway (force=true)")
                elif spec.dry_run:
                    warnings.append(f"{why}; submitting will be refused unless force=true")
                else:
                    raise GPUBusy({
                        "message": f"{why}. Pick a free GPU (GET /gpus) or pass force=true.",
                        "gpu": chosen.model_dump(), "gpus": [g.model_dump() for g in gpu_list.gpus],
                    })
            gpu_index = chosen.index

        sweep = bool(spec.parameters)
        runs = [{"index": i, "dir": f"{work_dir}/run_{i}" if sweep else work_dir,
                 "params": {k: str(v) for k, v in params.items()}}
                for i, params in enumerate(spec.parameters or [{}])]
        command = job_command(spec, python="python" if spec.venv else "python3")
        meta = {"job_id": job_id, "work_dir": work_dir, "log": log_path, "gpu": gpu_index,
                "command": command, "runs": [{"dir": r["dir"], "params": r["params"]} for r in runs]}
        script = _env.get_template("workstation.sh.j2").render(
            meta_json=json.dumps(meta), job_id=job_id, work_dir=work_dir, project_dir=project_dir,
            gpu=gpu_index, env=spec.env, venv_dir=venv_dir(project_dir, spec.venv) if spec.venv else None,
            seconds=spec.time_limit_seconds(), runs=runs, sweep=sweep, command=command,
        )
        script_path = f"{work_dir}/run.sh"
        array_size = len(runs) if sweep else None
        response = JobSubmitResponse(job_id=None, submitted=False, backend=self.name, script=script,
                                     script_path=script_path, work_dir=work_dir, array_size=array_size,
                                     gpu=gpu_index, warnings=warnings)
        if spec.dry_run:
            return response, None

        await conn.makedirs(work_dir)
        if spec.script is not None:
            await conn.write_file(f"{work_dir}/{spec.script_filename}", spec.script.encode())
        await conn.write_file(script_path, script.encode())
        result = await conn.run(launch_command(script_path, log_path), CMD_TIMEOUT)
        pids = _fields(result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "")
        if result.exit_code != 0 or not pids:
            raise HPCError(f"failed to launch job: {(result.stderr or result.stdout).strip() or 'no PID returned'}")
        response.job_id, response.submitted, response.pid = job_id, True, pids[0]
        return response, JobRecordData(job_id=job_id, work_dir=work_dir, script_path=script_path,
                                       array_size=array_size, pid=pids[0], gpu=gpu_index)

    async def _alive(self, conn: HPCConnection, pid: int) -> bool:
        return (await conn.run(f"kill -0 {pid}", CMD_TIMEOUT)).exit_code == 0

    async def job_status(self, conn: HPCConnection, job_id: str, record) -> JobStatus:
        if record is None:
            raise NotFound(f"job {job_id} was not submitted through this session")
        wd = record.work_dir
        pid_line, exit_line, cancelled = await asyncio.gather(
            _read_small(conn, f"{wd}/pid"), _read_small(conn, f"{wd}/exit_code"),
            _read_small(conn, f"{wd}/cancelled"),
        )
        pid_fields, exit_fields = _fields(pid_line), _fields(exit_line)
        pid = pid_fields[0] if pid_fields else record.pid
        started = pid_fields[1] if len(pid_fields) > 1 else None
        exit_code = ended = None
        alive = await self._alive(conn, pid) if pid and not exit_fields else False
        if pid and not exit_fields and not alive:
            # The process may finish after the first exit-file read. Re-read
            # after observing its exit before classifying it as lost.
            exit_fields = _fields(await _read_small(conn, f"{wd}/exit_code"))

        if exit_fields:
            exit_code = exit_fields[0]
            ended = exit_fields[1] if len(exit_fields) > 1 else None
            if exit_code == 0:
                state, raw = JobState.COMPLETED, "COMPLETED"
            elif cancelled:
                state, raw = JobState.CANCELLED, "CANCELLED"
            else:
                state, raw = JobState.FAILED, "TIMEOUT" if exit_code == 124 else "FAILED"
        elif alive:
            state, raw = JobState.RUNNING, "RUNNING"
        elif pid_line:
            # Process is gone without writing exit_code (SIGKILL, reboot, ...).
            state, raw = (JobState.CANCELLED, "CANCELLED") if cancelled else (JobState.FAILED, "LOST")
            exit_code = 137 if cancelled else None
        elif time.time() - record.submitted_at.timestamp() < START_GRACE_SECONDS:
            state, raw = JobState.PENDING, "STARTING"
        else:
            state, raw = JobState.FAILED, "NOT_STARTED"

        elapsed = _elapsed((ended or time.time()) - started) if started else None
        tasks = await self._runs(conn, record, state) if record.array_size else []
        return JobStatus(job_id=job_id, state=state, elapsed=elapsed, exit_code=exit_code,
                         tasks=tasks or [JobTask(task_id=job_id, state=state, raw_state=raw,
                                                 elapsed=elapsed, exit_code=exit_code)],
                         work_dir=wd, pid=pid, gpu=record.gpu)

    async def _runs(self, conn: HPCConnection, record, job_state: JobState) -> list[JobTask]:
        lines = await asyncio.gather(*(_read_small(conn, f"{record.work_dir}/run_{i}/exit_code")
                                       for i in range(record.array_size)))
        tasks, current_assigned = [], False
        for i, line in enumerate(lines):
            fields = _fields(line)
            if fields:
                code = fields[0]
                state = JobState.COMPLETED if code == 0 else JobState.FAILED
                tasks.append(JobTask(task_id=f"run_{i}", state=state, raw_state=state.value, exit_code=code))
            elif job_state in (JobState.RUNNING, JobState.PENDING):
                state = JobState.RUNNING if job_state == JobState.RUNNING and not current_assigned else JobState.PENDING
                current_assigned = True
                tasks.append(JobTask(task_id=f"run_{i}", state=state, raw_state=state.value))
            else:  # job ended before this run finished (cancelled / time limit)
                tasks.append(JobTask(task_id=f"run_{i}", state=job_state, raw_state="NOT_RUN"
                                     if job_state != JobState.CANCELLED else "CANCELLED"))
        return tasks

    async def cancel(self, conn: HPCConnection, job_id: str, record) -> None:
        if record is None:
            raise NotFound(f"job {job_id} was not submitted through this session")
        status = await self.job_status(conn, job_id, record)
        if status.state not in (JobState.RUNNING, JobState.PENDING) or not status.pid:
            return
        await conn.write_file(f"{record.work_dir}/cancelled", b"1")
        pid = status.pid
        await conn.run(f"kill -TERM -- -{pid}", CMD_TIMEOUT)  # whole process group (setsid)
        for _ in range(12):
            if not await self._alive(conn, pid):
                return
            await asyncio.sleep(0.25)
        child = _fields(await _read_small(conn, f"{record.work_dir}/child_pid"))
        targets = " ".join(f"-{p}" for p in [pid, *child[:1]])
        await conn.run(f"kill -KILL -- {targets}", CMD_TIMEOUT)

    def log_path(self, record, task: int) -> str:
        return f"{record.work_dir}/output.log"
