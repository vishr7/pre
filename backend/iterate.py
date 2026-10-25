"""Persistent, explicitly approved local Iterate studies.

The runner executes researcher supplied Python. It is intended for a trusted local
backend, not as an isolation boundary for untrusted code.
"""
import asyncio
import codecs
from contextlib import contextmanager
import hashlib
from importlib.metadata import distributions
import itertools
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
import optuna
from optuna.trial import TrialState
from pydantic import BaseModel, Field, model_validator


ROOT = Path(__file__).resolve().parent / "data" / "iterate"
router = APIRouter(prefix="/iterate", tags=["iterate"])
TASKS: dict[str, asyncio.Task] = {}
SUBSCRIBERS: dict[str, set[WebSocket]] = {}
# Terminal trials: the browser runs them in the user's SSH terminal tab and posts the output back.
TERMINAL_JOBS: dict[str, dict[int, dict]] = {}
TERMINAL_RESULTS: dict[tuple[str, int], asyncio.Future] = {}
METRICS_MARKER = "__PRE_ITERATE_METRICS__"


class Parameter(BaseModel):
    type: str
    low: float | None = None
    high: float | None = None
    step: int = 1
    log: bool = False
    choices: list[str | int | float | bool] | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.type == "categorical":
            if not self.choices or len(self.choices) > 32 or any(isinstance(x, float) and not math.isfinite(x) for x in self.choices):
                raise ValueError("Categorical choices must be nonempty and finite")
        elif self.type in ("int", "float"):
            if self.low is None or self.high is None or not all(map(math.isfinite, (self.low, self.high))) or self.low > self.high:
                raise ValueError("Numeric bounds must be finite and ordered")
            if self.log and self.low <= 0:
                raise ValueError("Logarithmic bounds must be positive")
            if self.type == "int" and (not self.low.is_integer() or not self.high.is_integer() or self.step < 1 or (self.high-self.low) % self.step or self.log and self.step != 1):
                raise ValueError("Invalid integer range or step")
        else:
            raise ValueError("Parameter type must be int, float, or categorical")
        return self


class Space(BaseModel):
    objective: dict[str, str]
    params: dict[str, Parameter] = Field(min_length=1, max_length=20)
    strategy: str = "bayesian"
    n_trials: int = Field(default=20, ge=1, le=100)
    parallel: int = Field(default=1, ge=1, le=8)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    seed: int = Field(default=42, ge=0, le=2**32-1)

    @model_validator(mode="after")
    def valid(self):
        import re
        if self.strategy not in ("grid", "random", "bayesian"):
            raise ValueError("Unknown search strategy")
        if self.objective.get("direction") not in ("minimize", "maximize") or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", self.objective.get("metric", "")):
            raise ValueError("Provide an objective metric and direction")
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) for name in self.params):
            raise ValueError("Parameter names must be identifiers")
        if self.strategy == "grid" and any(p.type == "float" for p in self.params.values()):
            raise ValueError("Grid search needs discrete parameters")
        if self.strategy == "grid" and any(p.type == "int" and (p.high-p.low)/p.step > 10000 for p in self.params.values()):
            raise ValueError("Grid dimensions must contain at most 10,000 values")
        return self


class Proposal(BaseModel):
    script: str = Field(min_length=1, max_length=200_000)
    space: Space
    remote: "RemoteConfig | None" = None
    via_terminal: bool = False
    parent_study: str | None = None
    parent_trial: int | None = None


class RemoteConfig(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    project: str = Field(default="iterate", pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    venv: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    partition: str | None = None
    account: str | None = None
    conda_env: str | None = None


Proposal.model_rebuild()


class TerminalResult(BaseModel):
    exit_code: int | None = None
    output: str = Field(default="", max_length=2_000_000)


class StartRequest(Proposal):
    approval_digest: str


def digest(proposal: Proposal) -> str:
    return hashlib.sha256(json.dumps(proposal.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@contextmanager
def connect():
    ROOT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / "results.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS studies (id TEXT PRIMARY KEY, spec TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, parent_study TEXT, parent_trial INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS trials (study_id TEXT, number INTEGER, parent_trial INTEGER, params TEXT, metrics TEXT, status TEXT, slot INTEGER, started REAL, duration REAL, run_dir TEXT, error TEXT, progress TEXT, seed INTEGER, script_sha256 TEXT, packages TEXT, PRIMARY KEY(study_id,number))")
    db.commit()
    try:
        with db:
            yield db
    finally:
        db.close()


def study_view(study_id):
    with connect() as db:
        study = db.execute("SELECT * FROM studies WHERE id=?", (study_id,)).fetchone()
        if not study:
            raise HTTPException(404, "Study not found")
        if study["status"] in ("RUNNING", "STOPPING") and study_id not in TASKS:
            db.execute("UPDATE studies SET status='FAILED' WHERE id=?", (study_id,))
            db.execute("UPDATE trials SET status='FAILED', error='Study process ended before trial completion' WHERE study_id=? AND status='RUNNING'", (study_id,))
            study = db.execute("SELECT * FROM studies WHERE id=?", (study_id,)).fetchone()
        trials = [dict(row) for row in db.execute("SELECT * FROM trials WHERE study_id=? ORDER BY number", (study_id,))]
        parent_row = db.execute("SELECT params FROM trials WHERE study_id=? AND number=?", (study["parent_study"], study["parent_trial"])).fetchone() if study["parent_study"] else None
    spec = json.loads(study["spec"])
    for row in trials:
        for key in ("params", "metrics", "progress", "packages"):
            row[key] = json.loads(row[key]) if row[key] else ({} if key != "progress" else [])
    metric, direction = spec["space"]["objective"]["metric"], spec["space"]["objective"]["direction"]
    completed = [row for row in trials if row["status"] == "COMPLETED"]
    best = min(completed, key=lambda x: x["metrics"][metric]) if completed and direction == "minimize" else max(completed, key=lambda x: x["metrics"][metric]) if completed else None
    return {"id": study_id, "status": study["status"], "space": spec["space"], "remote": spec.get("remote"), "via_terminal": spec.get("via_terminal", False), "parent_study": study["parent_study"], "parent_trial": study["parent_trial"], "parent_params": json.loads(parent_row["params"]) if parent_row else None, "trials": trials, "best": best}


async def publish(study_id):
    message = study_view(study_id)
    for socket in list(SUBSCRIBERS.get(study_id, ())):
        try:
            await socket.send_json(message)
        except Exception:
            SUBSCRIBERS[study_id].discard(socket)


def suggest(trial, params):
    result = {}
    for name, p in params.items():
        if p.type == "int":
            result[name] = trial.suggest_int(name, int(p.low), int(p.high), step=p.step, log=p.log)
        elif p.type == "float":
            result[name] = trial.suggest_float(name, p.low, p.high, log=p.log)
        else:
            result[name] = trial.suggest_categorical(name, p.choices)
    return result


def fits_space(config, params):
    for name, spec in params.items():
        value = config.get(name)
        if spec.type == "categorical":
            if value not in spec.choices:
                return False
        elif not isinstance(value, (int, float)) or isinstance(value, bool) or not spec.low <= value <= spec.high:
            return False
        elif spec.type == "int" and (not isinstance(value, int) or (value-spec.low) % spec.step):
            return False
    return True


def valid_metrics(metrics, objective):
    if not isinstance(metrics, dict):
        return False
    score = metrics.get(objective)
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
        return False
    try:
        json.dumps(metrics, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def hpc_manager():
    if __package__:
        from .hpc.router import get_manager
    else:
        from hpc.router import get_manager
    return get_manager()


async def remote_trial(study_id, trial, params, space, script, remote, slot, seed, run_dir, progress):
    if __package__:
        from .hpc.models import JobSpec
        from .hpc.store import JobRecord
    else:
        from hpc.models import JobSpec
        from hpc.store import JobRecord
    manager = hpc_manager()
    record, conn = await manager.connection(remote.session_id)
    args = []
    for name, value in params.items():
        args.extend((f"--{name}", str(value)))
    args.extend(("--out", "."))
    seconds = space.timeout_seconds
    time_limit = f"{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d}"
    python = "python3" if manager.compute.name == "workstation" and not remote.venv else "python"
    command = (f"({python} -m pip freeze > package_versions.txt 2>/dev/null || true); "
               f"{python} --version > python_version.txt 2>&1; "
               f'{python} "$PRE_JOB_DIR/train.py"')
    spec = JobSpec(job_name=f"iterate-{study_id[:8]}-{trial.number}", project=remote.project,
                   script=script, script_filename="train.py", command=command, args=args,
                   gpu=slot if manager.compute.name == "workstation" else "none",
                   gpus=1 if manager.compute.name == "slurm" else 0,
                   venv=remote.venv, partition=remote.partition, account=remote.account,
                   conda_env=remote.conda_env, time_limit=time_limit,
                   env={"PRE_TRIAL_SEED": str(seed)})
    ctx = await manager.context(record)
    response, data = await manager.compute.submit_job(conn, ctx, spec)
    if data is None or response.job_id is None:
        raise RuntimeError("Remote trial was not submitted")
    job = JobRecord(job_id=data.job_id, session_id=remote.session_id, backend=manager.compute.name,
                    job_name=spec.job_name, project=spec.project, work_dir=data.work_dir,
                    script_path=data.script_path, array_size=data.array_size, pid=data.pid, gpu=data.gpu)
    await manager.store.save_job(job)
    with connect() as db:
        db.execute("UPDATE trials SET run_dir=?, slot=? WHERE study_id=? AND number=?", (data.work_dir, data.gpu if data.gpu is not None else slot, study_id, trial.number))
    log_path = manager.compute.log_path(job, 0)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    offset, tail = 0, ""
    deadline = time.monotonic() + space.timeout_seconds + 30
    state = "FAILED"
    try:
        with (run_dir / "stdout.log").open("w", encoding="utf-8", newline="") as output:  # keep line endings as received
            while True:
                chunk = await conn.read_from(log_path, offset)
                if chunk:
                    offset += len(chunk)
                    decoded = decoder.decode(chunk)
                    output.write(decoded)
                    tail += decoded
                    lines = tail.split("\n")
                    tail = lines.pop()
                    for line in lines:
                        if len(progress) >= 1000:
                            break
                        try:
                            point = json.loads(line)
                            value = point.get(space.objective["metric"])
                            if isinstance(point.get("epoch"), int) and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                                progress.append(point)
                                trial.report(float(value), point["epoch"])
                                if trial.should_prune():
                                    await manager.compute.cancel(conn, data.job_id, job)
                                    return "PRUNED", None, None
                                with connect() as db:
                                    db.execute("UPDATE trials SET progress=? WHERE study_id=? AND number=?", (json.dumps(progress), study_id, trial.number))
                                await publish(study_id)
                        except (ValueError, TypeError, AttributeError):
                            pass
                status = await manager.compute.job_status(conn, data.job_id, job)
                if status.state.value in ("COMPLETED", "FAILED", "CANCELLED"):
                    if status.state.value != "COMPLETED" or status.exit_code not in (None, 0):
                        return "FAILED", None, f"Remote job ended {status.state.value} (exit {status.exit_code})"
                    raw = await conn.read_file(f"{data.work_dir}/metrics.json", 1_000_000)
                    metrics = json.loads(raw)
                    if not valid_metrics(metrics, space.objective["metric"]):
                        raise ValueError("Remote metrics.json needs a finite numeric objective and valid JSON metrics")
                    packages = {"collection_status": "unavailable"}
                    try:
                        frozen = (await conn.read_file(f"{data.work_dir}/package_versions.txt", 1_000_000)).decode("utf-8", "replace")
                        packages = dict(line.split("==", 1) for line in frozen.splitlines() if "==" in line)
                        packages["python"] = (await conn.read_file(f"{data.work_dir}/python_version.txt", 1000)).decode("utf-8", "replace").strip()
                    except Exception:
                        pass
                    with connect() as db:
                        db.execute("UPDATE trials SET packages=? WHERE study_id=? AND number=?", (json.dumps(packages), study_id, trial.number))
                    return "COMPLETED", metrics, None
                if time.monotonic() >= deadline:
                    await manager.compute.cancel(conn, data.job_id, job)
                    return "FAILED", None, "Remote trial time limit reached"
                await asyncio.sleep(min(manager.settings.poll_interval, 3))
    except BaseException:
        try:
            await manager.compute.cancel(conn, data.job_id, job)
        except Exception:
            pass
        raise


async def execute_trial(study_id, trial, params, space, script_hash, slot, parent_trial, proposal):
    run_dir = ROOT / study_id / f"trial_{trial.number}"
    run_dir.mkdir(parents=True, exist_ok=False)
    seed = (space.seed + trial.number) % (2**32)
    started = time.time()
    packages = {distribution.metadata["Name"]: distribution.version for distribution in distributions() if distribution.metadata.get("Name")} if not proposal.remote else {"collection_status": "pending"}
    if not proposal.remote:
        packages["python"] = sys.version.split()[0]
    with connect() as db:
        db.execute("INSERT INTO trials VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (study_id, trial.number, parent_trial, json.dumps(params), None, "RUNNING", slot, started, None, str(run_dir), None, "[]", seed, script_hash, json.dumps(packages)))
    await publish(study_id)
    progress, error, metrics, state = [], None, None, "FAILED"
    try:
        if proposal.via_terminal:
            state, metrics, error = await terminal_trial(study_id, trial, params, space, proposal.script, seed, run_dir, progress)
        elif proposal.remote:
            state, metrics, error = await remote_trial(study_id, trial, params, space, proposal.script, proposal.remote, slot, seed, run_dir, progress)
        else:
            state, metrics, error = await local_trial(trial, params, space, slot, seed, run_dir, progress, study_id)
    except (Exception, asyncio.CancelledError) as exc:
        error = str(exc)[:500]
        if isinstance(exc, asyncio.CancelledError):
            state = "CANCELLED"
    with connect() as db:
        db.execute("UPDATE trials SET status=?, metrics=?, duration=?, error=?, progress=? WHERE study_id=? AND number=?", (state, json.dumps(metrics) if metrics else None, time.time()-started, error, json.dumps(progress), study_id, trial.number))
    await publish(study_id)
    return state, metrics


def terminal_code(study_id, number, script, args, seed, timeout):
    """Python run by the terminal's remote interpreter: runs train.py in its own folder, then prints metrics."""
    import base64
    folder = f"~/pre-iterate/{study_id[:8]}/trial_{number}"
    return f"""import base64, json, os, subprocess, sys
d = os.path.expanduser({json.dumps(folder)})
os.makedirs(d, exist_ok=True)
p = os.path.join(d, "train.py")
with open(p, "wb") as f:
    f.write(base64.b64decode({json.dumps(base64.b64encode(script.encode()).decode())}))
env = dict(os.environ, PRE_TRIAL_SEED={json.dumps(str(seed))}, PYTHONUNBUFFERED="1")
try:
    code = subprocess.run([sys.executable, p, *{json.dumps(args)}, "--out", d], cwd=d, env=env, timeout={timeout}).returncode
except subprocess.TimeoutExpired:
    print("Trial time limit reached", file=sys.stderr)
    code = 124
try:
    with open(os.path.join(d, "metrics.json")) as f:
        print({json.dumps(METRICS_MARKER)}, json.dumps(json.load(f)))
except (OSError, ValueError):
    pass
sys.exit(code)
"""


def parse_terminal_output(output, space, progress):
    metrics, lines = None, []
    for line in output.replace("\r", "").split("\n"):
        if line.startswith(METRICS_MARKER):
            try:
                metrics = json.loads(line[len(METRICS_MARKER):])
            except ValueError:
                pass
            continue
        lines.append(line)
        try:
            point = json.loads(line)
            value = point.get(space.objective["metric"]) if isinstance(point, dict) else None
            if len(progress) < 1000 and isinstance(point.get("epoch"), int) and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                progress.append(point)
        except (ValueError, AttributeError):
            pass
    return metrics, "\n".join(lines)


async def terminal_trial(study_id, trial, params, space, script, seed, run_dir, progress):
    args = []
    for name, value in params.items():
        args.extend((f"--{name}", str(value)))
    future = asyncio.get_running_loop().create_future()
    TERMINAL_RESULTS[(study_id, trial.number)] = future
    TERMINAL_JOBS.setdefault(study_id, {})[trial.number] = {
        "number": trial.number, "claimed": False,
        "code": terminal_code(study_id, trial.number, script, args, seed, space.timeout_seconds)}
    await publish(study_id)
    try:
        # Extra minute: the browser has to pick the trial up and the terminal may be slow.
        result = await asyncio.wait_for(future, space.timeout_seconds + 60)
    except asyncio.TimeoutError:
        return "FAILED", None, "No result from the terminal. Keep PRE open with the terminal logged in over SSH."
    finally:
        TERMINAL_JOBS.get(study_id, {}).pop(trial.number, None)
        TERMINAL_RESULTS.pop((study_id, trial.number), None)
    metrics, output = parse_terminal_output(result.output, space, progress)
    (run_dir / "stdout.log").write_text(output, encoding="utf-8")
    if result.exit_code != 0:
        tail = [line for line in output.splitlines() if line.strip()]
        detail = f": {tail[-1].strip()}" if tail else ""
        return "FAILED", None, (f"Script exited with code {result.exit_code}" if result.exit_code is not None else "Terminal run failed") + detail
    if metrics is None:
        return "FAILED", None, "Script finished but did not write metrics.json to the --out folder"
    if not valid_metrics(metrics, space.objective["metric"]):
        return "FAILED", None, "metrics.json needs a finite numeric objective and valid JSON metrics"
    return "COMPLETED", metrics, None


async def local_trial(trial, params, space, slot, seed, run_dir, progress, study_id):
    process = None
    state, metrics, error = "FAILED", None, None
    args = [sys.executable, str(ROOT / study_id / "train.py")]
    for name, value in params.items():
        args.extend((f"--{name}", str(value)))
    args.extend(("--out", str(run_dir)))
    try:
        # Non-secret basics only (no API keys); Windows tools and getpass need the user/OS names too.
        inherited = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL", "VIRTUAL_ENV",
                     "USER", "USERNAME", "LOGNAME", "HOMEDRIVE", "HOMEPATH", "SYSTEMDRIVE", "COMSPEC", "PATHEXT",
                     "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"}
        env = {key: value for key, value in os.environ.items() if key.upper() in inherited}
        env["PYTHONUNBUFFERED"] = "1"
        env["PRE_TRIAL_SEED"] = str(seed)
        # A slot bounds local concurrency. GPU assignment belongs to a GPU-aware backend.
        stderr_file = (run_dir / "stderr.log").open("wb")
        process = await asyncio.create_subprocess_exec(*args, cwd=run_dir, env=env, stdout=asyncio.subprocess.PIPE, stderr=stderr_file)
        deadline = time.monotonic() + space.timeout_seconds
        with (run_dir / "stdout.log").open("w", encoding="utf-8", newline="") as log:  # child output is already \r\n on Windows
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Trial time limit reached")
                line = await asyncio.wait_for(process.stdout.readline(), remaining)
                if not line:
                    break
                decoded = line.decode("utf-8", "replace")[:10000]
                log.write(decoded)
                if len(progress) < 1000:
                    try:
                        point = json.loads(decoded)
                        if isinstance(point, dict) and isinstance(point.get("epoch"), int) and isinstance(point.get(space.objective["metric"]), (int, float)) and math.isfinite(point[space.objective["metric"]]):
                            progress.append(point)
                            trial.report(float(point[space.objective["metric"]]), point["epoch"])
                            if trial.should_prune():
                                state = "PRUNED"
                                break
                            with connect() as db:
                                db.execute("UPDATE trials SET progress=? WHERE study_id=? AND number=?", (json.dumps(progress), study_id, trial.number))
                            await publish(study_id)
                    except (ValueError, TypeError):
                        pass
        if state == "PRUNED":
            process.kill()
        await asyncio.wait_for(process.wait(), max(0.01, deadline-time.monotonic()))
        if state != "PRUNED":
            if process.returncode != 0:
                stderr_file.close()
                tail = [line for line in (run_dir / "stderr.log").read_text("utf-8", "replace").splitlines() if line.strip()]
                error = f"Script exited with code {process.returncode}" + (f": {tail[-1].strip()}" if tail else "")
            elif not (run_dir / "metrics.json").is_file():
                raise ValueError("Script finished but did not write metrics.json to the --out folder")
            else:
                metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
                if not valid_metrics(metrics, space.objective["metric"]):
                    raise ValueError("metrics.json needs a finite numeric objective and valid JSON metrics")
                state = "COMPLETED"
    except (Exception, asyncio.CancelledError) as exc:
        error = str(exc)[:500]
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        if isinstance(exc, asyncio.CancelledError):
            state = "CANCELLED"
    finally:
        if "stderr_file" in locals():
            stderr_file.close()
    return state, metrics, error


async def _run_study(study_id, proposal):
    space = proposal.space
    dimensions = {name: list(range(int(p.low), int(p.high)+1, p.step)) if p.type == "int" else p.choices for name, p in space.params.items()} if space.strategy == "grid" else {}
    if space.strategy == "grid":
        sampler = optuna.samplers.RandomSampler(seed=space.seed)
        budget = min(space.n_trials, math.prod(map(len, dimensions.values())))
    elif space.strategy == "random":
        sampler, budget = optuna.samplers.RandomSampler(seed=space.seed), space.n_trials
    else:
        sampler, budget = optuna.samplers.TPESampler(seed=space.seed), space.n_trials
    storage = f"sqlite:///{(ROOT / study_id / 'optuna.sqlite3').as_posix()}"
    study = optuna.create_study(direction=space.objective["direction"], sampler=sampler, storage=storage, study_name=study_id, load_if_exists=True, pruner=optuna.pruners.MedianPruner())
    parent_cfg = None
    parent_queued = False
    if proposal.parent_study is not None:
        parent = study_view(proposal.parent_study)["trials"]
        parent_cfg = next(row["params"] for row in parent if row["number"] == proposal.parent_trial)
        if fits_space(parent_cfg, space.params):
            try:
                study.enqueue_trial({name: parent_cfg[name] for name in space.params})
                parent_queued = True
            except ValueError:
                pass
    if space.strategy == "grid":
        names = list(dimensions)
        queued = 1 if parent_queued else 0
        for values in itertools.product(*(dimensions[name] for name in names)):
            config = dict(zip(names, values))
            if parent_queued and all(config[name] == parent_cfg[name] for name in names):
                continue
            if queued >= budget:
                break
            study.enqueue_trial(config)
            queued += 1
    script_hash = hashlib.sha256(proposal.script.encode()).hexdigest()
    (ROOT / study_id / "train.py").write_text(proposal.script, encoding="utf-8")
    if proposal.via_terminal:
        slots = [0]  # one terminal runs one command at a time
    elif proposal.remote:
        manager = hpc_manager()
        record, conn = await manager.connection(proposal.remote.session_id)
        if manager.compute.name == "workstation":
            gpu_list = await manager.compute.gpus(conn, await manager.context(record))
            slots = [gpu.index for gpu in gpu_list.gpus if not gpu.busy][:space.parallel]
            if not slots:
                raise RuntimeError("No free remote GPUs are available")
        else:
            slots = list(range(space.parallel))
    else:
        slots = list(range(space.parallel))
    lock = asyncio.Lock()
    count = 0
    async def worker(slot):
        nonlocal count
        while True:
            async with lock:
                with connect() as db:
                    stopped = db.execute("SELECT status FROM studies WHERE id=?", (study_id,)).fetchone()[0] == "STOPPING"
                if count >= budget or stopped:
                    return
                count += 1
                trial = study.ask()
                params = suggest(trial, space.params)
            state, metrics = await execute_trial(study_id, trial, params, space, script_hash, slot, proposal.parent_trial, proposal)
            async with lock:
                optuna_state = TrialState.COMPLETE if state == "COMPLETED" else TrialState.PRUNED if state == "PRUNED" else TrialState.FAIL
                study.tell(trial, metrics[space.objective["metric"]] if state == "COMPLETED" else None, state=optuna_state)
    try:
        await asyncio.gather(*(worker(slot) for slot in slots[:budget]))
        with connect() as db:
            stopped = db.execute("SELECT status FROM studies WHERE id=?", (study_id,)).fetchone()[0] == "STOPPING"
            successes = db.execute("SELECT COUNT(*) FROM trials WHERE study_id=? AND status='COMPLETED'", (study_id,)).fetchone()[0]
            db.execute("UPDATE studies SET status=? WHERE id=?", ("STOPPED" if stopped else "COMPLETED" if successes else "FAILED", study_id))
    except Exception:
        with connect() as db:
            db.execute("UPDATE studies SET status='FAILED' WHERE id=?", (study_id,))
        raise
    finally:
        await publish(study_id)
        TASKS.pop(study_id, None)


async def run_study(study_id, proposal):
    try:
        await _run_study(study_id, proposal)
    except Exception:
        with connect() as db:
            db.execute("UPDATE studies SET status='FAILED' WHERE id=?", (study_id,))
        await publish(study_id)
        TASKS.pop(study_id, None)


class NextRound(BaseModel):
    space: Space
    rationale: str = Field(min_length=1, max_length=2000)


@router.post("/studies/{study_id}/suggest")
async def suggest_next_round(study_id: str):
    view = study_view(study_id)
    completed = [row for row in view["trials"] if row["status"] == "COMPLETED"]
    if len(completed) < 2:
        raise HTTPException(422, "At least two completed trials are needed")
    metric = view["space"]["objective"]["metric"]
    descending = view["space"]["objective"]["direction"] == "maximize"
    ranked = sorted(completed, key=lambda row: row["metrics"][metric], reverse=descending)
    failed = [{"params": row["params"], "error": row["error"]} for row in view["trials"] if row["status"] == "FAILED"]
    importance = {}
    try:
        study = optuna.load_study(study_name=study_id, storage=f"sqlite:///{(ROOT / study_id / 'optuna.sqlite3').as_posix()}")
        importance = optuna.importance.get_param_importances(study)
    except Exception:
        pass
    summary = {"objective": view["space"]["objective"], "completed": len(completed), "top": [{"params": row["params"], "score": row["metrics"][metric]} for row in ranked[:5]], "bottom": [{"params": row["params"], "score": row["metrics"][metric]} for row in ranked[-3:]], "failed": failed[:5], "importance": importance, "original_space": view["space"]}
    try:
        if __package__:
            from .ai.gemini import structured_call
        else:
            from ai.gemini import structured_call
        proposed = await asyncio.to_thread(structured_call, json.dumps(summary), NextRound,
            "Propose a narrower next search space and short rationale from measured trial evidence. Return JSON only. Keep the objective metric and direction, parameter names and types, and trial limits. Do not claim a new study has run.")
    except Exception as exc:
        raise HTTPException(503, f"AI suggestion unavailable: {type(exc).__name__}") from exc
    old = Space.model_validate(view["space"])
    new = proposed.space
    if new.objective != old.objective or set(new.params) != set(old.params) or any(new.params[name].type != old.params[name].type for name in old.params):
        raise HTTPException(422, "Suggested space changed the objective or parameter schema")
    for name, original in old.params.items():
        updated = new.params[name]
        if original.type == "categorical" and not set(map(str, updated.choices)).issubset(set(map(str, original.choices))):
            raise HTTPException(422, "Suggested categorical choices exceed the original space")
        if original.type != "categorical" and (updated.low < original.low or updated.high > original.high):
            raise HTTPException(422, "Suggested numeric bounds exceed the original space")
    return {"summary": summary, "proposal": proposed.model_dump(), "requires_approval": True}


@router.get("/health")
def health():
    """Lets the Iterate screen tell 'backend not running' apart from other errors."""
    return {"status": "ok"}


@router.post("/preview")
def preview(proposal: Proposal):
    return {"digest": digest(proposal), "trials": proposal.space.n_trials, "parallel": 1 if proposal.via_terminal else proposal.space.parallel, "execution": "your SSH terminal session" if proposal.via_terminal else "connected HPC job" if proposal.remote else "trusted local Python subprocess"}


@router.post("/studies")
async def start(request: StartRequest):
    proposal = Proposal.model_validate(request.model_dump(exclude={"approval_digest"}))
    if request.approval_digest != digest(proposal):
        raise HTTPException(409, "Proposal changed since approval")
    if proposal.via_terminal and proposal.remote:
        raise HTTPException(422, "Choose either the terminal or an HPC session, not both")
    if proposal.remote:
        await hpc_manager().connection(proposal.remote.session_id)
    if proposal.parent_study is not None:
        parent = study_view(proposal.parent_study)
        if proposal.parent_trial is None or not any(t["number"] == proposal.parent_trial and t["status"] == "COMPLETED" for t in parent["trials"]):
            raise HTTPException(422, "Select a completed parent trial")
    study_id = uuid4().hex
    (ROOT / study_id).mkdir(parents=True)
    with connect() as db:
        db.execute("INSERT INTO studies VALUES (?,?,?,?,?,?)", (study_id, proposal.model_dump_json(), "RUNNING", time.time(), proposal.parent_study, proposal.parent_trial))
    TASKS[study_id] = asyncio.create_task(run_study(study_id, proposal))
    return study_view(study_id)


@router.get("/studies/{study_id}")
def get_study(study_id: str):
    return study_view(study_id)


@router.get("/studies/{study_id}/analysis")
def analysis(study_id: str):
    view = study_view(study_id)
    completed = [row for row in view["trials"] if row["status"] == "COMPLETED"]
    importance = {}
    if len(completed) >= 2:
        try:
            study = optuna.load_study(study_name=study_id, storage=f"sqlite:///{(ROOT / study_id / 'optuna.sqlite3').as_posix()}")
            importance = optuna.importance.get_param_importances(study)
        except Exception:
            pass
    return {"importance": importance, "coordinates": [{"number": row["number"], "params": row["params"], "score": row["metrics"][view["space"]["objective"]["metric"]]} for row in completed]}


@router.get("/studies/{study_id}/trials/{number}/logs")
def trial_logs(study_id: str, number: int):
    view = study_view(study_id)
    trial = next((row for row in view["trials"] if row["number"] == number), None)
    if trial is None:
        raise HTTPException(404, "Trial not found")
    directory = ROOT / study_id / f"trial_{number}"
    logs = {}
    for name in ("stdout", "stderr"):
        path = directory / f"{name}.log"
        if path.is_file():
            with path.open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 65536))
                logs[name] = stream.read().decode("utf-8", "replace")
        else:
            logs[name] = ""
    return logs


@router.get("/studies/{study_id}/terminal/next")
def terminal_next(study_id: str):
    """Hands the browser the next trial to run in its SSH terminal, or null when none is waiting."""
    for job in TERMINAL_JOBS.get(study_id, {}).values():
        if not job["claimed"]:
            job["claimed"] = True
            return {"number": job["number"], "code": job["code"]}
    return None


@router.post("/studies/{study_id}/terminal/{number}")
def terminal_result(study_id: str, number: int, result: TerminalResult):
    future = TERMINAL_RESULTS.get((study_id, number))
    if future is None or future.done():
        raise HTTPException(404, "That trial is not waiting for a terminal result")
    future.set_result(result)
    return {"ok": True}


@router.post("/studies/{study_id}/stop")
def stop(study_id: str):
    study_view(study_id)
    with connect() as db:
        db.execute("UPDATE studies SET status='STOPPING' WHERE id=? AND status='RUNNING'", (study_id,))
    return study_view(study_id)


@router.websocket("/studies/{study_id}/live")
async def live(websocket: WebSocket, study_id: str):
    await websocket.accept()
    try:
        await websocket.send_json(study_view(study_id))
        SUBSCRIBERS.setdefault(study_id, set()).add(websocket)
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, HTTPException):
        pass
    finally:
        SUBSCRIBERS.get(study_id, set()).discard(websocket)
