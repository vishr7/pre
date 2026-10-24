"""Fake machine with the same transport interface as asyncssh (HPC_MOCK=true).

It answers the shell commands both compute backends send, so the real WorkstationBackend /
SlurmBackend logic runs unchanged on top of it:
- workstation: `setsid nohup bash run.sh` starts a simulated process (RUNNING -> COMPLETED
  over HPC_MOCK_PENDING_SECONDS + HPC_MOCK_RUN_SECONDS, ~30s), `kill`, `nvidia-smi` with
  two GPUs (GPU 0 busy with another user's job, GPU 1 free), pyenv, venv python/pip.
- slurm: sbatch / squeue / sacct / scancel with PENDING -> RUNNING -> COMPLETED.
Jobs write a growing training log and, when done, results.csv / metrics.json / loss_curve.png.

Mock auth rules: a host ending in ".invalid" is unreachable, password "wrong" fails, and with
HPC_MOCK_2FA=true the first hop (the jump host if any) asks for Duo: "1" (push) or 6 digits.
"""

import asyncio
import json
import math
import posixpath
import random
import re
import shlex
import struct
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .backend import (
    AuthFailed, ChallengeHandler, CommandResult, HostUnreachable, HPCBackend, HPCConnection,
    InvalidRequest, NotFound, PayloadTooLarge,
)
from .config import HPCSettings
from .models import AuthPrompt, ConnectRequest, FileInfo

EPOCHS = 20
OTHER_USER_PID = 2211
FAKE_GPUS = [  # (uuid, name, base util %, base memory MiB, total MiB)
    ("GPU-3f1c9a2e-0000-4b1d-9a77-aaaaaaaaaaaa", "NVIDIA RTX A6000", 87, 30215, 49140),
    ("GPU-7b2d4c6f-1111-4e8a-8c55-bbbbbbbbbbbb", "NVIDIA RTX A6000", 0, 4, 49140),
]


@dataclass
class _MockJob:
    """A SLURM job."""

    job_id: str
    name: str
    work_dir: str
    output: str               # --output pattern
    command: str
    array_size: int | None
    params: list[dict[str, str]]
    submitted: float = field(default_factory=time.monotonic)
    cancelled_at: float | None = None
    results_written: set[int] = field(default_factory=set)


@dataclass
class _MockProc:
    """A workstation background job started by `setsid nohup bash run.sh`."""

    pid: int
    meta: dict                # parsed from the wrapper's "# PRE-JOB {...}" line
    started: float = field(default_factory=time.monotonic)
    started_wall: int = field(default_factory=lambda: int(time.time()))
    ended: bool = False
    cancelled: bool = False
    runs_done: set[int] = field(default_factory=set)


class MockConnection(HPCConnection):
    _next_job_id = 4815162
    _next_pid = 31337

    def __init__(self, username: str, settings: HPCSettings):
        self.settings = settings
        self.username = username
        self.home = f"/storage/home/{username}"
        self.files: dict[str, bytes] = {}
        self.mtimes: dict[str, float] = {}
        self.dirs: set[str] = set()
        self.jobs: dict[str, _MockJob] = {}
        self.procs: dict[int, _MockProc] = {}
        self._alive = True
        self._mkdirs(self.home)
        self._mkdirs(settings.base_dir)

    # ---- filesystem ----

    def _abs(self, path: str) -> str:
        path = path or "."
        if path.startswith("~"):
            path = self.home + path[1:]
        if not path.startswith("/"):
            path = f"{self.home}/{path}"
        return posixpath.normpath(path)

    def _mkdirs(self, path: str) -> None:
        while path not in ("/", ""):
            self.dirs.add(path)
            path = posixpath.dirname(path)

    def _write(self, path: str, data: bytes) -> None:
        if posixpath.dirname(path) not in self.dirs:
            raise NotFound(f"remote path not found: {posixpath.dirname(path)}")
        self.files[path] = data
        self.mtimes[path] = time.time()

    def _children(self, path: str) -> list[FileInfo]:
        out = []
        for d in self.dirs:
            if posixpath.dirname(d) == path and d != path:
                out.append(FileInfo(name=posixpath.basename(d), path=d, size=4096, is_dir=True))
        for f, data in self.files.items():
            if posixpath.dirname(f) == path:
                out.append(FileInfo(name=posixpath.basename(f), path=f, size=len(data), is_dir=False,
                                    modified=datetime.fromtimestamp(self.mtimes[f], timezone.utc)))
        return sorted(out, key=lambda f: (not f.is_dir, f.name))

    async def realpath(self, path: str) -> str:
        return self._abs(path)

    async def makedirs(self, path: str) -> None:
        self._mkdirs(self._abs(path))

    async def write_file(self, path: str, data: bytes) -> None:
        self._write(self._abs(path), data)

    async def read_file(self, path: str, max_bytes: int) -> bytes:
        self._tick()
        p = self._abs(path)
        if p in self.dirs:
            raise InvalidRequest(f"{path} is a directory")
        if p not in self.files:
            raise NotFound(f"remote path not found: {path}")
        if len(self.files[p]) > max_bytes:
            raise PayloadTooLarge(f"{path} is larger than {max_bytes // (1024 * 1024)} MB")
        return self.files[p]

    async def read_from(self, path: str, offset: int, max_bytes: int = 65536) -> bytes:
        self._tick()
        return self.files.get(self._abs(path), b"")[offset:offset + max_bytes]

    async def listdir(self, path: str) -> list[FileInfo]:
        self._tick()
        p = self._abs(path)
        if p not in self.dirs:
            raise NotFound(f"remote path not found: {path}")
        return self._children(p)

    def is_alive(self) -> bool:
        return self._alive

    async def close(self) -> None:
        self._alive = False

    # ---- commands ----

    async def run(self, command: str, timeout: float) -> CommandResult:
        await asyncio.sleep(0.02)
        self._tick()
        try:
            argv = shlex.split(command)
        except ValueError as e:
            return CommandResult("", f"bash: {e}\n", 2)
        if not argv:
            return CommandResult("", "", 0)
        base = posixpath.basename(argv[0])
        if "/" in argv[0] and re.fullmatch(r"python3?(\.\d+)?|pip3?", base):
            return self._venv_tool(argv)
        handler = getattr(self, f"_cmd_{argv[0].replace('-', '_')}", None)
        if handler is None:
            return CommandResult("", f"bash: {argv[0]}: command not found\n", 127)
        return handler(argv[1:])

    async def stream(self, command: str, timeout: float):
        if command.startswith("# PRE-ENV "):
            async for item in self._env_setup(json.loads(command.split("\n", 1)[0][len("# PRE-ENV "):])):
                yield item
            return
        r = await self.run(command, timeout)
        if r.stdout or r.stderr:
            yield ("output", r.stdout + r.stderr)
        yield ("exit", r.exit_code)

    async def _env_setup(self, meta: dict):
        venv, version = meta["venv"], meta.get("python_version") or "3.11.9"
        lines = []
        if meta.get("python_version"):
            lines.append(f"[PRE] pyenv install -s {version}")
        lines += [f"[PRE] creating venv with Python {version}",
                  "Requirement already satisfied: pip in ./venvs (24.0)",
                  "Successfully installed pip-24.2"]
        for req in meta["requirements"]:
            name = re.split(r"[<>=!~\[; ]", req, maxsplit=1)[0]
            lines += [f"Collecting {req}", f"  Downloading {name}-1.0.0-py3-none-any.whl (1.2 MB)"]
        if meta["requirements"]:
            names = " ".join(re.split(r"[<>=!~\[; ]", r, maxsplit=1)[0] + "-1.0.0" for r in meta["requirements"])
            lines.append(f"Successfully installed {names}")
        lines.append(f"[PRE] environment ready: {venv}")
        for line in lines:
            await asyncio.sleep(0.05)
            yield ("output", line + "\n")
        self._mkdirs(f"{venv}/bin")
        for tool in ("python", "python3", "pip", "activate"):
            self._write(f"{venv}/bin/{tool}", b"")
        self._write(f"{venv}/requirements.lock", "\n".join(meta["requirements"]).encode())
        self.files[f"{venv}/version"] = version.encode()
        yield ("exit", 0)

    def _venv_tool(self, argv: list[str]) -> CommandResult:
        path = self._abs(argv[0])
        if path not in self.files:
            return CommandResult("", f"bash: {argv[0]}: No such file or directory\n", 127)
        venv = posixpath.dirname(posixpath.dirname(path))
        version = self.files.get(f"{venv}/version", b"3.11.9").decode()
        if "--version" in argv or "-V" in argv:
            if posixpath.basename(path).startswith("pip"):
                return CommandResult(f"pip 24.2 from {venv}/lib/python{version[:4]}/site-packages/pip\n", "", 0)
            return CommandResult(f"Python {version}\n", "", 0)
        if "list" in argv or "freeze" in argv:
            reqs = self.files.get(f"{venv}/requirements.lock", b"").decode().split()
            return CommandResult("".join(f"{r}==1.0.0\n" for r in reqs), "", 0)
        return CommandResult("", "", 0)

    def _cmd_ls(self, args: list[str]) -> CommandResult:
        targets = [a for a in args if not a.startswith("-")] or ["."]
        out = []
        for t in targets:
            p = self._abs(t)
            if p in self.files:
                out.append(posixpath.basename(p))
            elif p in self.dirs:
                out.extend(f.name + ("/" if f.is_dir else "") for f in self._children(p))
            else:
                return CommandResult("", f"ls: cannot access '{t}': No such file or directory\n", 2)
        return CommandResult("\n".join(out) + ("\n" if out else ""), "", 0)

    def _cmd_cat(self, args: list[str]) -> CommandResult:
        out = []
        for t in args:
            p = self._abs(t)
            if p not in self.files:
                return CommandResult("".join(out), f"cat: {t}: No such file or directory\n", 1)
            out.append(self.files[p].decode(errors="replace"))
        return CommandResult("".join(out), "", 0)

    def _cmd_tail(self, args: list[str]) -> CommandResult:
        n, paths, i = 10, [], 0
        while i < len(args):
            a = args[i]
            if a in ("-n", "--lines") and i + 1 < len(args):
                n, i = int(args[i + 1].lstrip("+")), i + 2
                continue
            if a.startswith("-n") and a[2:].isdigit():
                n = int(a[2:])
            elif not a.startswith("-"):
                paths.append(a)
            i += 1
        out = []
        for t in paths:
            p = self._abs(t)
            if p not in self.files:
                return CommandResult("", f"tail: cannot open '{t}' for reading: No such file or directory\n", 1)
            out += self.files[p].decode(errors="replace").splitlines()[-n:]
        return CommandResult("\n".join(out) + ("\n" if out else ""), "", 0)

    def _cmd_mkdir(self, args: list[str]) -> CommandResult:
        for t in (a for a in args if not a.startswith("-")):
            self._mkdirs(self._abs(t))
        return CommandResult("", "", 0)

    def _cmd_module(self, args: list[str]) -> CommandResult:
        sub = args[0] if args else "list"
        if sub in ("avail", "spider"):
            text = ("---- /sw/modulefiles ----\n   anaconda/2023.09   cuda/12.1   gcc/13.2.0\n"
                    "   python/3.11.2      pytorch/2.3   openmpi/4.1.6\n")
        elif sub == "list":
            text = "Currently Loaded Modules:\n  1) gcc/13.2.0\n"
        else:
            text = ""
        return CommandResult("", text, 0)  # Lmod writes to stderr

    def _cmd_pyenv(self, args: list[str]) -> CommandResult:
        if not args or args[0] == "versions":
            return CommandResult("  system\n* 3.11.9 (set by /home/user/.pyenv/version)\n  3.10.14\n", "", 0)
        if args[0] == "install":
            return CommandResult(f"Downloading Python-{args[-1]}.tar.xz...\nInstalled Python-{args[-1]}\n", "", 0)
        return CommandResult("", "", 0)

    def _cmd_ps(self, args: list[str]) -> CommandResult:
        lines = ["    PID TTY          TIME CMD", f"{OTHER_USER_PID:>7} ?        05:12:44 python"]
        for p in self.procs.values():
            if self._proc_alive(p):
                lines.append(f"{p.pid:>7} ?        00:00:{int(time.monotonic() - p.started) % 60:02d} bash")
        return CommandResult("\n".join(lines) + "\n", "", 0)

    def _cmd_nvidia_smi(self, args: list[str]) -> CommandResult:
        busy_on = {}
        for p in self.procs.values():
            if self._proc_alive(p) and p.meta.get("gpu") is not None:
                busy_on.setdefault(p.meta["gpu"], []).append(p.pid)
        query = next((a for a in args if a.startswith("--query-")), "")
        lines = []
        for i, (uuid, name, util, mem, total) in enumerate(FAKE_GPUS):
            ours = busy_on.get(i, [])
            if query.startswith("--query-gpu"):
                lines.append(f"{i}, {uuid}, {name}, {mem + 9000 * len(ours)}, {total}, "
                             f"{min(100, util + 95 * len(ours))}")
            elif query.startswith("--query-compute-apps"):
                if i == 0:
                    lines.append(f"{OTHER_USER_PID}, {uuid}, 30200 MiB")
                lines += [f"{pid}, {uuid}, 9000 MiB" for pid in ours]
        if not query:
            return CommandResult("+-----------------------------------------------+\n"
                                 "| NVIDIA-SMI 550.54     CUDA Version: 12.4      |\n", "", 0)
        return CommandResult("\n".join(lines) + ("\n" if lines else ""), "", 0)

    def _cmd_setsid(self, args: list[str]) -> CommandResult:
        # setsid nohup bash <run.sh> > <log> 2>&1 < /dev/null & echo $!
        if len(args) < 3 or args[:2] != ["nohup", "bash"] or self._abs(args[2]) not in self.files:
            return CommandResult("", "setsid: failed to execute\n", 1)
        script = self.files[self._abs(args[2])].decode()
        m = re.search(r"^# PRE-JOB (.*)$", script, re.MULTILINE)
        if not m:
            return CommandResult("", "mock: not a PRE wrapper script\n", 1)
        pid = MockConnection._next_pid
        MockConnection._next_pid += 1
        proc = _MockProc(pid=pid, meta=json.loads(m.group(1)))
        self.procs[pid] = proc
        self._write(proc.meta["log"], b"")
        self._write(f"{proc.meta['work_dir']}/pid", f"{pid} {proc.started_wall}\n".encode())
        self._tick()
        return CommandResult(f"{pid}\n", "", 0)

    def _cmd_kill(self, args: list[str]) -> CommandResult:
        signal, targets = "TERM", []
        for a in args:
            if a == "--":
                continue
            if a.startswith("-") and not a[1:].isdigit():
                signal = a[1:].upper()
            elif a.startswith("-") and int(a[1:]) <= 64 and not targets and "--" not in args:
                signal = a[1:]
            else:
                targets.append(abs(int(a)))
        for t in targets:
            proc = self.procs.get(t)
            if proc is None or not self._proc_alive(proc):
                return CommandResult("", f"bash: kill: ({t}) - No such process\n", 1)
            if signal != "0":
                proc.cancelled = True
                self._tick()
        return CommandResult("", "", 0)

    # ---- slurm commands ----

    def _cmd_sbatch(self, args: list[str]) -> CommandResult:
        paths = [a for a in args if not a.startswith("-")]
        if not paths or self._abs(paths[-1]) not in self.files:
            return CommandResult("", "sbatch: error: Unable to open file\n", 1)
        script = self.files[self._abs(paths[-1])].decode()
        directives = dict(re.findall(r"^#SBATCH --([\w-]+)=(\S+)", script, re.MULTILINE))
        if "partition" in directives and directives["partition"] == "nonexistent":
            return CommandResult("", "sbatch: error: invalid partition specified: nonexistent\n", 1)
        work_dir = self._abs(directives.get("chdir", "."))
        if work_dir not in self.dirs:
            return CommandResult("", f"sbatch: error: chdir to {work_dir} failed\n", 1)
        array_size = None
        if m := re.match(r"0-(\d+)", directives.get("array", "")):
            array_size = int(m.group(1)) + 1
        sweep = {name: shlex.split(vals) for name, vals in
                 re.findall(r"^(\w+)_VALUES=\((.*)\)$", script, re.MULTILINE)}
        params = [{k: v[i] for k, v in sweep.items() if i < len(v)} for i in range(array_size or 1)]
        body = script.split("started on", 1)[-1].splitlines()[1:2]
        job_id = str(MockConnection._next_job_id)
        MockConnection._next_job_id += 1
        self.jobs[job_id] = _MockJob(
            job_id=job_id, name=directives.get("job-name", "job"), work_dir=work_dir,
            output=self._abs(directives.get("output", f"{work_dir}/slurm-%j.out")),
            command=body[0] if body else "", array_size=array_size, params=params,
        )
        text = f"{job_id}\n" if "--parsable" in args else f"Submitted batch job {job_id}\n"
        return CommandResult(text, "", 0)

    def _cmd_scancel(self, args: list[str]) -> CommandResult:
        for a in args:
            job = self.jobs.get(a.split("_")[0])
            if job is None:
                return CommandResult("", f"scancel: error: Invalid job id {a}\n", 1)
            if job.cancelled_at is None and self._state(job)[0] != "COMPLETED":
                job.cancelled_at = time.monotonic()
        return CommandResult("", "", 0)

    def _rows(self, args: list[str]) -> list[tuple[str, str, float]]:
        ids = None
        if "-j" in args:
            ids = {a.split("_")[0] for a in args[args.index("-j") + 1].split(",")}
        rows = []
        for job in self.jobs.values():
            if ids is not None and job.job_id not in ids:
                continue
            state, elapsed = self._state(job)
            if job.array_size is None:
                rows.append((job.job_id, state, elapsed))
            else:
                rows.extend((f"{job.job_id}_{i}", state, elapsed) for i in range(job.array_size))
        return rows

    def _cmd_squeue(self, args: list[str]) -> CommandResult:
        rows = [r for r in self._rows(args) if r[1] in ("PENDING", "RUNNING")]
        if "-o" in args:
            lines = [f"{i}|{s}|{_short(e)}|{'Priority' if s == 'PENDING' else 'None'}" for i, s, e in rows]
        else:
            lines = [] if "-h" in args else ["   JOBID PARTITION     NAME     USER ST       TIME  NODES"]
            lines += [f"{i:>8}      open      job     user {s[:2]} {_short(e):>10}      1" for i, s, e in rows]
        return CommandResult("\n".join(lines) + ("\n" if lines else ""), "", 0)

    def _cmd_sacct(self, args: list[str]) -> CommandResult:
        lines = []
        for i, s, e in self._rows(args):
            code = "0:15" if s == "CANCELLED" else "0:0"
            raw = "CANCELLED by 0" if s == "CANCELLED" else s
            lines.append(f"{i}|{raw}|{_long(e)}|{code}")
        return CommandResult("\n".join(lines) + ("\n" if lines else ""), "", 0)

    # ---- simulation ----

    def _duration(self) -> float:
        return self.settings.mock_pending_seconds + self.settings.mock_run_seconds

    def _proc_alive(self, proc: _MockProc) -> bool:
        return not proc.ended and not proc.cancelled and time.monotonic() - proc.started < self._duration()

    def _state(self, job: _MockJob) -> tuple[str, float]:
        """SLURM job (state, elapsed run seconds) at the current moment."""
        p, r = self.settings.mock_pending_seconds, self.settings.mock_run_seconds
        now = job.cancelled_at or time.monotonic()
        t = now - job.submitted
        running = max(0.0, min(t - p, r))
        if job.cancelled_at is not None:
            return "CANCELLED", running
        if t < p:
            return "PENDING", 0.0
        if t < p + r:
            return "RUNNING", running
        return "COMPLETED", r

    def _tick(self) -> None:
        """Bring every job's log and result files up to date."""
        for job in self.jobs.values():
            state, elapsed = self._state(job)
            if state == "PENDING":
                continue
            frac = elapsed / self.settings.mock_run_seconds if self.settings.mock_run_seconds else 1.0
            for task in range(job.array_size or 1):
                self._write_slurm_task(job, task, state, frac)
        for proc in self.procs.values():
            if not proc.ended:
                self._advance_proc(proc)

    def _advance_proc(self, proc: _MockProc) -> None:
        meta, runs = proc.meta, proc.meta["runs"]
        sweep = len(runs) > 1 or runs[0]["dir"] != meta["work_dir"]
        per_run = self._duration() / len(runs)
        elapsed = time.monotonic() - proc.started
        finished = proc.cancelled or elapsed >= self._duration()
        lines = [f"[PRE] job {meta['job_id']} started on nittanyaicompute at "
                 f"{datetime.now().strftime('%a %b %d %H:%M:%S %Y')} (CUDA_VISIBLE_DEVICES="
                 f"{'' if meta['gpu'] is None else meta['gpu']})"]
        for i, run in enumerate(runs):
            start = i * per_run
            if elapsed < start and not (finished and not proc.cancelled):
                break
            if sweep:
                lines.append(f"[PRE] run {i + 1}/{len(runs)}: "
                             + " ".join(f"{k}={v}" for k, v in run["params"].items()))
            run_done = elapsed >= start + per_run or (finished and not proc.cancelled)
            frac = 1.0 if run_done else max(0.0, (elapsed - start) / per_run)
            curve = _curve(meta["job_id"], i, run["params"])
            lines += [f"epoch {e + 1:>2}/{EPOCHS}  loss={curve[e][0]:.4f}  accuracy={curve[e][1]:.4f}"
                      for e in range(EPOCHS if run_done else min(EPOCHS, int(frac * EPOCHS)))]
            if run_done and i not in proc.runs_done:
                proc.runs_done.add(i)
                self._mkdirs(run["dir"])
                _write_results(self, run["dir"], "", f"{meta['job_id']}/run_{i}", run["params"], curve)
                if sweep:
                    self._write(f"{run['dir']}/exit_code", f"0 {int(time.time())}\n".encode())
            if sweep and run_done:
                lines.append(f"[PRE] run {i + 1} finished with exit code 0")
            if not run_done:
                break
        if finished:
            code = 143 if proc.cancelled else 0
            if proc.cancelled:
                lines.append("[PRE] cancelled")
            lines.append(f"[PRE] job finished with exit code {code} at {datetime.now().strftime('%c')}")
            self._write(f"{meta['work_dir']}/exit_code", f"{code} {int(time.time())}\n".encode())
            proc.ended = True
        self._write(meta["log"], ("\n".join(lines) + "\n").encode())

    def _write_slurm_task(self, job: _MockJob, task: int, state: str, frac: float) -> None:
        params = job.params[task] if task < len(job.params) else {}
        curve = _curve(job.job_id, task, params)
        done = EPOCHS if state == "COMPLETED" else min(EPOCHS, int(frac * EPOCHS))
        task_id = f"{job.job_id}_{task}" if job.array_size else job.job_id
        lines = [f"[PRE] job {task_id} started on mock-node-{task % 4 + 1:02d} at "
                 f"{datetime.now().strftime('%a %b %d %H:%M:%S %Y')}",
                 f"$ {job.command}".rstrip()]
        if params:
            lines.append("params: " + " ".join(f"{k}={v}" for k, v in params.items()))
        lines += [f"epoch {e + 1:>2}/{EPOCHS}  loss={curve[e][0]:.4f}  accuracy={curve[e][1]:.4f}"
                  for e in range(done)]
        if state == "CANCELLED":
            lines.append(f"slurmstepd: error: *** JOB {task_id} CANCELLED ***")
        if state == "COMPLETED":
            lines.append(f"[PRE] job {task_id} finished")
        log_path = (job.output.replace("%A", job.job_id).replace("%a", str(task))
                    .replace("%j", task_id))
        self._write(log_path, ("\n".join(lines) + "\n").encode())
        if state == "COMPLETED" and task not in job.results_written:
            job.results_written.add(task)
            _write_results(self, job.work_dir, f"_task{task}" if job.array_size else "", task_id, params, curve)


def _write_results(conn: MockConnection, directory: str, suffix: str, label: str,
                   params: dict, curve: list[tuple[float, float]]) -> None:
    csv = "epoch,loss,accuracy\n" + "".join(
        f"{e + 1},{loss:.4f},{acc:.4f}\n" for e, (loss, acc) in enumerate(curve))
    metrics = {"job_id": label, "params": params, "epochs": EPOCHS,
               "final_loss": round(curve[-1][0], 4), "final_accuracy": round(curve[-1][1], 4)}
    conn._write(f"{directory}/results{suffix}.csv", csv.encode())
    conn._write(f"{directory}/metrics{suffix}.json", json.dumps(metrics, indent=2).encode())
    conn._write(f"{directory}/loss_curve{suffix}.png", _plot_png([c[0] for c in curve]))


def _short(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _long(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}"


def _curve(job_id: str, task: int, params: dict[str, str]) -> list[tuple[float, float]]:
    """Deterministic, plausible training curve; a numeric param (e.g. LR) shapes the decay."""
    rng = random.Random(f"{job_id}-{task}")
    rate = 0.18
    for v in params.values():
        try:
            rate = min(0.4, max(0.05, 0.18 * (1 + 0.3 * math.log10(float(v) / 0.001))))
            break
        except ValueError:  # non-numeric, or log of <= 0
            continue
    out = []
    for e in range(EPOCHS):
        loss = 0.15 + 2.15 * math.exp(-rate * (e + 1)) + rng.uniform(-0.02, 0.02)
        acc = min(0.995, 0.1 + 0.88 * (1 - math.exp(-rate * 1.2 * (e + 1))) + rng.uniform(-0.01, 0.01))
        out.append((max(loss, 0.01), max(acc, 0.0)))
    return out


def _plot_png(values: list[float], w: int = 240, h: int = 140) -> bytes:
    """Tiny dependency-free line chart (grayscale PNG)."""
    px = [[255] * w for _ in range(h)]
    lo, hi = min(values), max(values)
    pad = 12
    for x in range(pad, w - pad):           # axes
        px[h - pad][x] = 120
    for y in range(pad, h - pad + 1):
        px[y][pad] = 120
    pts = [(pad + i * (w - 2 * pad) // (len(values) - 1),
            (h - pad) - int((v - lo) / ((hi - lo) or 1) * (h - 2 * pad))) for i, v in enumerate(values)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for s in range(steps + 1):
            x, y = x0 + (x1 - x0) * s // steps, y0 + (y1 - y0) * s // steps
            for dy in (-1, 0, 1):
                if 0 <= y + dy < h:
                    px[y + dy][x] = 30
    raw = b"".join(b"\x00" + bytes(row) for row in px)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


class MockBackend(HPCBackend):
    def __init__(self, settings: HPCSettings):
        self.settings = settings

    async def connect(self, req: ConnectRequest, challenge: ChallengeHandler) -> HPCConnection:
        hops = ([("jump host", req.jump_host)] if req.jump_host else []) + [("target", req.host)]
        for i, (kind, host) in enumerate(hops):
            label = f"{kind} {host}" + (f" (via {req.jump_host})" if kind == "target" and req.jump_host else "")
            await asyncio.sleep(0.1)
            if host.endswith(".invalid"):
                raise HostUnreachable(f"{label}: could not connect on port 22 (gaierror)")
            if req.private_key_path and not self.settings.allow_key_paths:
                raise InvalidRequest("private_key_path is disabled on this server "
                                     "(set HPC_ALLOW_KEY_PATHS=true); upload the key instead")
            if req.password and req.password.get_secret_value() == "wrong":
                raise AuthFailed(f"{label}: authentication failed (check username, password/key, or 2FA response)")
            if self.settings.mock_2fa and i == 0:  # Duo on the first hop
                answers = await challenge(
                    host,
                    f"Duo two-factor login for {req.username}\n\nEnter a passcode or select one of "
                    "the following options:\n\n 1. Duo Push to XXX-XXX-1234",
                    [AuthPrompt(prompt="Passcode or option (1-1): ", echo=True)],
                )
                answer = answers[0].strip() if answers else ""
                if answer == "1":
                    await asyncio.sleep(0.5)  # "approving" the push
                elif not re.fullmatch(r"\d{6}", answer):
                    raise AuthFailed(f"{label}: authentication failed (check username, password/key, or 2FA response)")
        return MockConnection(req.username, self.settings)
