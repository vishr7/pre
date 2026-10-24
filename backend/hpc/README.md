# PRE HPC: remote GPU workstation + SLURM integration

A FastAPI router (`/hpc`) that lets a researcher connect over SSH, check GPUs, set up a Python environment, upload files, launch experiments (including parameter sweeps), stream logs live, and download results.

Two compute backends, chosen with `COMPUTE_BACKEND`:

| | `workstation` (default) | `slurm` |
|---|---|---|
| Machine | Penn State **Nittany AI Compute** (`nittanyaicompute.ist.psu.edu`), reached through the jump host `ssh.ist.psu.edu` | A SLURM cluster such as Roar Collab (`submit.hpc.psu.edu`) |
| Jobs | Detached background processes (`setsid nohup`) tracked by PID | `sbatch`, tracked by squeue/sacct |
| GPUs | Shared. `nvidia-smi` is checked before each launch | Requested with `--gres` |
| Sweeps | Variations run **sequentially** on one GPU, each in `run_<i>/` | Job array |
| Work dir | `/data/pre/<user>/<project>/` | `~/pre-projects/<project>/` |

`HPC_MOCK=true` replaces SSH with a fake machine that answers the same shell commands: Duo on the jump hop, two GPUs (one busy, one free), and jobs that finish in about 30s with a training log and CSV/JSON/PNG results. The real backend code runs unchanged on top of it, so every endpoint behaves the same in mock mode.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r hpc/requirements.txt      # Windows (macOS/Linux: .venv/bin/pip)
.venv/Scripts/uvicorn hpc.main:app --reload --port 8002
# docs: http://localhost:8002/docs
.venv/Scripts/python -m pytest hpc/tests -q             # mock machine + in-process SSH servers
```

Settings live in the repository-root `.env` (see `.env.example`). The standalone `main.py` loads only this module's variables from it.

| Variable | Default | Meaning |
|---|---|---|
| `HPC_MOCK` | `false` | Use the fake machine |
| `HPC_MOCK_2FA` | `true` | Mock asks for Duo on the first hop (answer `1` or any 6 digits) |
| `HPC_MOCK_PENDING_SECONDS` / `HPC_MOCK_RUN_SECONDS` | `8` / `22` | Mock job timeline (the workstation runs for the sum) |
| `COMPUTE_BACKEND` | `workstation` | `workstation` or `slurm` |
| `JUMP_HOST` | `ssh.ist.psu.edu` (workstation), none (slurm) | Set it empty to connect directly |
| `TARGET_HOST` | `nittanyaicompute.ist.psu.edu` / `submit.hpc.psu.edu` | Default host for `/connect` |
| `BASE_DIR` | `/data/pre` | Workstation root. Everything lives under `$BASE_DIR/<user>/` |
| `GPU_BUSY_UTIL_PERCENT` / `GPU_BUSY_MEMORY_MB` | `10` / `1024` | A GPU is busy if utilization or memory used is above these |
| `HPC_REMOTE_BASE_DIR` | `pre-projects` | SLURM project root (relative to `$HOME`) |
| `HPC_CONNECT_TIMEOUT` | `60` | Seconds per connect/2FA step (leave time to approve a Duo push) |
| `HPC_AUTH_TIMEOUT` | `180` | Seconds the handshake waits for a 2FA answer |
| `HPC_KEEPALIVE_INTERVAL` | `30` | SSH keepalive (both hops) |
| `HPC_STRICT_HOST_KEYS` / `HPC_KNOWN_HOSTS` | `true` / `~/.ssh/known_hosts` | Host key checking |
| `HPC_ALLOW_KEY_PATHS` | `false` | Allow `private_key_path`, which reads a key from the PRE server's disk (local dev only) |
| `HPC_EXEC_MAX_TIMEOUT` / `HPC_ENV_TIMEOUT` | `300` / `1800` | Max seconds for `/exec` / `/env` |
| `HPC_MAX_DOWNLOAD_MB` | `100` | Upload/download size limit |
| `HPC_POLL_INTERVAL` | `5` | WebSocket poll period |

### Manual check before using the real machine

Run this once from the machine that runs PRE. It confirms your access, completes Duo, and adds both host keys to `~/.ssh/known_hosts`, which strict host-key checking needs:

```bash
ssh -J <psu-id>@ssh.ist.psu.edu <psu-id>@nittanyaicompute.ist.psu.edu
# then on the workstation:
nvidia-smi
ls -ld /data/pre            # must exist and be writable (ask the admins if not)
pyenv versions
```

## Mounting into the main app

```python
from hpc.router import router as hpc_router, shutdown_hpc

app.include_router(hpc_router)       # add the Auth0 dependency before deployment
# on shutdown: await shutdown_hpc()  # closes SSH connections
```

Requirements: `asyncssh`, `Jinja2` (see `hpc/requirements.txt`). The router has no auth of its own. A `session_id` is an unguessable token, but put `dependencies=[Depends(require_user)]` on `include_router` before deploying. The `HPC_*`, `COMPUTE_BACKEND`, `JUMP_HOST`, `TARGET_HOST`, `BASE_DIR`, and `GPU_BUSY_*` variables are read from `os.environ`.

## Connecting (two hops, 2FA on either)

1. `POST /hpc/connect` with `{"username": "<psu-id>", "password": "..."}`. `host` and `jump_host` default from `.env`. PRE connects to the jump host, then tunnels to the target, using the same credentials on both. Password prompts are answered automatically.
2. If a hop asks for Duo, the response is `{"status": "awaiting_2fa", "hop": "ssh.ist.psu.edu", "prompts": [...]}`. Show the prompt, then `POST /hpc/connect/{id}/respond` with `{"responses": ["1"]}` (push) or a passcode.
3. If the next hop also asks, you get another `awaiting_2fa` with that `hop`. Otherwise you get `connected`. The connection is reused until `DELETE /hpc/sessions/{id}`.

Errors name the hop that failed, e.g. `jump host ssh.ist.psu.edu: authentication failed` or `target nittanyaicompute.ist.psu.edu (via ssh.ist.psu.edu): could not connect on port 22`. Passwords, keys, and 2FA codes stay in memory only for the handshake. They are never logged, stored, or returned.

## Endpoints

All under `/hpc`. Errors come back as `{"detail": ...}`.

| Method & path | Purpose |
|---|---|
| `GET /health` | Mode, backend, default hosts |
| `POST /connect` · `POST /connect/{sid}/respond` | Connect, answer 2FA prompts |
| `GET /sessions` · `GET /sessions/{sid}/status` · `DELETE /sessions/{sid}` | Sessions |
| `GET /sessions/{sid}/gpus` | Per-GPU stats, processes, busy/free (workstation; 501 on slurm) |
| `POST /sessions/{sid}/env` | Create `<project>/venvs/<name>` and pip install. Streams NDJSON |
| `POST /sessions/{sid}/exec` | One allowlisted command → stdout/stderr/exit code |
| `PUT /sessions/{sid}/projects/{project}/files/{path}` | Upload the raw body |
| `GET /sessions/{sid}/projects/{project}/files?path=` | List files |
| `GET /sessions/{sid}/projects/{project}/files/{path}` | Download a file |
| `POST /sessions/{sid}/jobs` | Generate the job script and launch it (or `dry_run`) |
| `GET /sessions/{sid}/jobs` | Jobs submitted in this session |
| `GET /sessions/{sid}/jobs/{job_id}` | Status: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, or `CANCELLED`, plus runs/tasks |
| `POST /sessions/{sid}/jobs/{job_id}/cancel` | Workstation: TERM (then KILL) the process group. Slurm: scancel |
| `WS /sessions/{sid}/jobs/{job_id}/stream` | Live status and log tail |
| `GET /sessions/{sid}/jobs/{job_id}/results?ext=csv,json,png` | Files in the job directory and `run_<i>/` |
| `GET /sessions/{sid}/jobs/{job_id}/results/{path}` | Download a result |

Status codes: `400` bad input or path, `401` auth failed (per hop), `403` command not allowed or outside `BASE_DIR`, `404` unknown session/job/file, `409` not connected, nothing awaiting 2FA, or **GPU busy**, `413` too large, `422` invalid spec or SLURM rejected the job, `501` not supported on this backend, `502` host unreachable (per hop), untrusted host key, or nvidia-smi failed, `504` timeout.

### GPUs

`GET /gpus` runs:

```
nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits
nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader
```

`uuid` is added to the first query so processes can be matched to GPUs. Each GPU reports `busy`, `busy_reasons`, and `processes`. A process has `ours: true` when a PRE job in this session started it.

### Workstation jobs

```json
{
  "job_name": "train-mnist",
  "project": "mnist",
  "script": "...optional file contents, uploaded into the job dir as script_filename...",
  "script_filename": "train.py",
  "args": ["--epochs", "20", "--lr", "$LR"],
  "gpu": "auto",
  "venv": "default",
  "time_limit": "02:00:00",
  "env": {"SEED": "42"},
  "parameters": [{"LR": 0.1}, {"LR": 0.01}],
  "force": false,
  "dry_run": false
}
```

- **Command.** By default the job runs `python <script> <args>`. With `script` the file is uploaded into the job dir. Without it, the file must already be in the project dir (upload it with `/files`). Pass `command` to run something else. Args are shell-quoted, so `$LR` inside one stays literal. To use a sweep parameter as an argument, write it into `command` instead, e.g. `"command": "python $PRE_PROJECT_DIR/train.py --lr $LR"`.
- **GPU.** An index sets `CUDA_VISIBLE_DEVICES`. `"auto"` picks the least-loaded free GPU, and `"none"` runs on CPU. If the chosen GPU is busy, you get **HTTP 409** with `{"message", "gpu", "gpus"}` unless `force: true`. `dry_run` reports a busy GPU as a warning instead.
- **Venv.** `venv` activates `<project>/venvs/<name>`, created with `/env`.
- **Wrapper.** The job launches as `setsid nohup bash run.sh > output.log 2>&1 &`. The wrapper (`templates/workstation.sh.j2`, returned in `script`):
  - writes `pid` and runs the command under `timeout`, with a deadline covering the whole job;
  - writes `exit_code` at the end: 124 for the time limit, 143 when cancelled;
  - forwards TERM to `timeout`'s process group.

  Status is computed from `kill -0 <pid>` plus those files.
- **Sweeps.** `parameters` run one after another on the same GPU, in `run_0/`, `run_1/`, and so on. Each run gets its values as environment variables, plus `$PRE_RUN_DIR` and `$PRE_RUN_INDEX`, and writes its own `exit_code`. A failed run doesn't stop the sweep. The job's exit code is the first non-zero one. `tasks` in the status response shows each run.
- **Ignored fields.** SLURM-only fields (`partition`, `account`, `modules`, `conda_env`, `nodes`, …) are ignored on the workstation, with a warning.
- **Environment.** `$PRE_JOB_DIR` and `$PRE_PROJECT_DIR` are exported, and `PYTHONUNBUFFERED=1` is set so the log streams.

### Environment setup

```bash
curl -N -X POST $B/sessions/$SID/env -H 'content-type: application/json' \
  -d '{"project":"mnist","name":"default","python_version":"3.11.9","requirements":["torch","numpy>=2"]}'
{"type": "output", "data": "[PRE] creating venv with Python 3.11.9\n"}
...
{"type": "done", "exit_code": 0, "venv": "/data/pre/<user>/mnist/venvs/default"}
```

`python_version` is optional (`pyenv install -s`, then that interpreter). Otherwise `python3` is used. Requirement strings may not start with `-`, so no pip options.

### `/exec` allowlist

All commands reject shell operators, globs, `$`, and `~`, and are re-quoted with shlex.

- **workstation:** `nvidia-smi` (it can't write files), `ps`, `pyenv`, and `kill` (only PIDs of PRE jobs in this session). Also `ls`, `cat`, `tail`, and `mkdir` with paths inside `$BASE_DIR/<user>`: relative paths resolve there and anything outside returns 403. Finally, `python`/`pip` only from `<project>/venvs/<name>/bin/`, e.g. `mnist/venvs/default/bin/python --version`. No sudo, docker, or module.
- **slurm:** `sbatch squeue sacct scancel ls cat mkdir module`.

### WebSocket messages

```json
{"type": "status", "job_id": "...", "state": "RUNNING", "pid": 31337, "gpu": 1, "tasks": [...]}
{"type": "log", "data": "epoch  3/20  loss=1.21  accuracy=0.61\n"}
{"type": "done", "state": "COMPLETED", "exit_code": 0}
{"type": "error", "status": 404, "detail": "..."}
```

## Example (mock mode, workstation)

```bash
B=localhost:8002/hpc
SID=$(curl -s -X POST $B/connect -H 'content-type: application/json' \
  -d '{"username":"abc123","password":"..."}' | jq -r .session_id)     # status: awaiting_2fa, hop: ssh.ist.psu.edu
curl -s -X POST $B/connect/$SID/respond -H 'content-type: application/json' -d '{"responses":["1"]}'

curl -s $B/sessions/$SID/gpus | jq '.gpus[] | {index, busy, busy_reasons}'
curl -sN -X POST $B/sessions/$SID/env -H 'content-type: application/json' -d '{"project":"mnist","requirements":["torch"]}'
curl -s -T train.py $B/sessions/$SID/projects/mnist/files/train.py

# GPU 0 is busy in the mock -> 409
curl -s -X POST $B/sessions/$SID/jobs -H 'content-type: application/json' \
  -d '{"job_name":"t","project":"mnist","script_filename":"train.py","gpu":0}'

JOB=$(curl -s -X POST $B/sessions/$SID/jobs -H 'content-type: application/json' -d '{
  "job_name":"lr-sweep","project":"mnist","venv":"default",
  "command":"python $PRE_PROJECT_DIR/train.py --lr $LR",
  "parameters":[{"LR":0.1},{"LR":0.01},{"LR":0.001}]}' | jq -r .job_id)

curl -s $B/sessions/$SID/jobs/$JOB
websocat ws://localhost:8002/hpc/sessions/$SID/jobs/$JOB/stream
curl -s "$B/sessions/$SID/jobs/$JOB/results?ext=csv,png"
curl -s -O $B/sessions/$SID/jobs/$JOB/results/run_0/results.csv
curl -s -X DELETE $B/sessions/$SID
```

Mock-only test inputs: a host ending in `.invalid` is unreachable (on either hop), the password `wrong` fails auth, and on slurm `partition: "nonexistent"` makes sbatch reject the job.

## Layout

```
hpc/
  router.py          FastAPI endpoints
  models.py          Pydantic models and validation
  backend.py         interfaces: transport (HPCBackend/HPCConnection) + ComputeBackend; HTTP errors
  ssh_client.py      asyncssh transport (jump host tunnel), SessionManager (connect, 2FA relay, reuse)
  workstation.py     WorkstationBackend: nvidia-smi, GPU selection, PID jobs, env setup, allowlist
  slurm.py           SlurmBackend: sbatch rendering, squeue/sacct parsing
  mock_backend.py    fake machine for both backends
  store.py           session/job metadata store (in-memory; swap for Postgres)
  config.py          settings
  templates/         workstation.sh.j2 (wrapper), job.sbatch.j2
  main.py            standalone dev app
  tests/             pytest
```

To move state to Postgres, implement `store.Store` and pass it in `router.get_manager()`. Live SSH connections stay in memory, so a server restart means users reconnect (and redo 2FA). Running jobs keep going and their files remain on disk.
