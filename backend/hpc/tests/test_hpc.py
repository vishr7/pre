"""Workstation backend (default) + shared endpoints, all against the mock machine."""

import asyncio
import json
import shlex
import shutil
import subprocess

import pytest

from hpc.backend import Forbidden, InvalidRequest, JobContext, job_command
from hpc.config import load_hpc_settings
from hpc.models import JobSpec
from hpc.ssh_client import _Client, parse_user_command, safe_relpath
from hpc.workstation import WorkstationBackend, build_gpu_list, parse_compute_apps, parse_gpus, pick_gpu

from .conftest import make_client, read_stream, wait_for_state

CREDS = {"username": "abc123", "password": "hunter2"}
BASE = "/data/pre/abc123"


@pytest.fixture
def client(monkeypatch):
    with make_client(monkeypatch) as c:
        yield c


@pytest.fixture
def session(client):
    r = client.post("/hpc/connect", json=CREDS)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "connected"
    return r.json()["session_id"]


def submit(client, session, **spec):
    body = {"job_name": "train", "project": "mnist", "script": "print('training')\n", **spec}
    return client.post(f"/hpc/sessions/{session}/jobs", json=body)


# ---------- connection ----------

def test_connect_defaults_to_workstation_via_jump_host(client, session):
    status = client.get(f"/hpc/sessions/{session}/status").json()
    assert status["host"] == "nittanyaicompute.ist.psu.edu"
    assert status["jump_host"] == "ssh.ist.psu.edu"
    assert status["backend"] == "workstation" and status["mock"] is True
    assert status["base_dir"] == BASE
    assert "hunter2" not in json.dumps(status)
    assert client.get("/hpc/health").json()["backend"] == "workstation"
    assert client.delete(f"/hpc/sessions/{session}").status_code == 204
    assert client.get(f"/hpc/sessions/{session}/status").status_code == 404


@pytest.mark.parametrize("body,code,text", [
    ({**CREDS, "jump_host": "jump.invalid"}, 502, "jump host jump.invalid"),
    ({**CREDS, "host": "gpu.invalid"}, 502, "target gpu.invalid (via ssh.ist.psu.edu)"),
    ({**CREDS, "host": "gpu.invalid", "jump_host": ""}, 502, "target gpu.invalid:"),
    ({**CREDS, "password": "wrong"}, 401, "jump host ssh.ist.psu.edu: authentication failed"),
    ({"username": "abc123"}, 422, None),
    ({"username": "abc123", "private_key_path": "~/.ssh/id_ed25519"}, 400, "HPC_ALLOW_KEY_PATHS"),
])
def test_connect_errors_name_the_hop(client, body, code, text):
    r = client.post("/hpc/connect", json=body)
    assert r.status_code == code, r.text
    if text:
        assert text in r.json()["detail"]


def test_two_factor_on_jump_hop(monkeypatch):
    with make_client(monkeypatch, HPC_MOCK_2FA="true") as client:
        r = client.post("/hpc/connect", json=CREDS).json()
        assert r["status"] == "awaiting_2fa" and r["hop"] == "ssh.ist.psu.edu"
        assert "Duo" in r["instructions"]
        sid = r["session_id"]
        assert client.post(f"/hpc/sessions/{sid}/gpus").status_code == 405
        assert client.get(f"/hpc/sessions/{sid}/gpus").status_code == 409  # not connected yet
        assert client.post(f"/hpc/connect/{sid}/respond", json={"responses": []}).status_code == 400
        r = client.post(f"/hpc/connect/{sid}/respond", json={"responses": ["1"]}).json()
        assert r["status"] == "connected" and r["hop"] is None
        assert client.post(f"/hpc/connect/{sid}/respond", json={"responses": ["1"]}).status_code == 409

        # Without a jump host the target itself asks.
        r = client.post("/hpc/connect", json={**CREDS, "jump_host": ""}).json()
        assert r["hop"] == "nittanyaicompute.ist.psu.edu"
        bad = client.post(f"/hpc/connect/{r['session_id']}/respond", json={"responses": ["nope"]})
        assert bad.status_code == 401 and "target nittanyaicompute" in bad.json()["detail"]


def test_real_client_answers_password_and_forwards_duo_with_hop():
    forwarded = []

    async def challenge(hop, instructions, prompts):
        forwarded.append((hop, instructions, [p.prompt for p in prompts]))
        return ["1"]

    async def scenario():
        c = _Client("pw", challenge, "ssh.ist.psu.edu")
        assert await c.kbdint_challenge_received("", "", "", []) == []
        assert await c.kbdint_challenge_received("", "", "", [("Password: ", False)]) == ["pw"]
        assert await c.kbdint_challenge_received("Duo", "Pick", "", [("Passcode or option: ", True)]) == ["1"]
        assert c.password_auth_requested() is None  # password is only ever sent once per hop

    asyncio.run(scenario())
    assert forwarded == [("ssh.ist.psu.edu", "Duo\nPick", ["Passcode or option: "])]


# ---------- GPUs ----------

GPU_CSV = """0, GPU-aaaa, NVIDIA RTX A6000, 30215, 49140, 87
1, GPU-bbbb, NVIDIA RTX A6000, 4, 49140, 0
2, GPU-cccc, Tesla V100-SXM2-32GB, 1500, 32768, 3
3, GPU-dddd, NVIDIA A100, [N/A], 81920, [N/A]
"""
APPS_CSV = """2211, GPU-aaaa, 30200 MiB
31337, GPU-cccc, 1490 MiB
"""


def test_nvidia_smi_parsing():
    gpus = parse_gpus(GPU_CSV)
    assert gpus[0] == {"index": 0, "uuid": "GPU-aaaa", "name": "NVIDIA RTX A6000", "memory_used_mb": 30215,
                       "memory_total_mb": 49140, "utilization_percent": 87}
    assert gpus[3]["memory_used_mb"] is None and gpus[3]["utilization_percent"] is None
    assert parse_compute_apps(APPS_CSV) == [(2211, "GPU-aaaa", 30200), (31337, "GPU-cccc", 1490)]
    assert parse_compute_apps("No running processes found\n") == []
    assert parse_gpus("") == []

    infos = build_gpu_list(GPU_CSV, APPS_CSV, util_threshold=10, mem_threshold=1024, our_pids={31337})
    assert [g.busy for g in infos] == [True, False, True, False]
    assert infos[0].busy_reasons == ["utilization 87% > 10%", "memory used 30215 MB > 1024 MB"]
    assert infos[2].busy_reasons == ["memory used 1500 MB > 1024 MB"]
    assert [(p.pid, p.ours) for p in infos[2].processes] == [(31337, True)]
    assert [(p.pid, p.ours) for p in infos[0].processes] == [(2211, False)]

    assert pick_gpu(infos, "auto").index == 1  # known-idle beats free-with-[N/A]-stats (GPU 3)
    assert pick_gpu(infos, 2).index == 2
    with pytest.raises(InvalidRequest):
        pick_gpu(infos, 9)
    with pytest.raises(InvalidRequest):
        pick_gpu([], "auto")


def test_gpu_endpoint(client, session):
    body = client.get(f"/hpc/sessions/{session}/gpus").json()
    assert body["busy_util_percent"] == 10 and body["busy_memory_mb"] == 1024
    g0, g1 = body["gpus"]
    assert g0["busy"] is True and g0["processes"][0]["pid"] == 2211 and g0["processes"][0]["ours"] is False
    assert g1["busy"] is False and g1["processes"] == []


def test_gpu_thresholds_are_configurable(monkeypatch):
    with make_client(monkeypatch, GPU_BUSY_UTIL_PERCENT="95", GPU_BUSY_MEMORY_MB="40000") as client:
        sid = client.post("/hpc/connect", json=CREDS).json()["session_id"]
        assert [g["busy"] for g in client.get(f"/hpc/sessions/{sid}/gpus").json()["gpus"]] == [False, False]


# ---------- jobs ----------

def test_dry_run_wrapper_script(client, session):
    r = submit(client, session, dry_run=True, args=["--epochs", "20", "it's"], time_limit="00:30:00",
               venv="torch", env={"SEED": "42"}, partition="open", modules=["cuda"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submitted"] is False and body["job_id"] is None and body["backend"] == "workstation"
    assert body["gpu"] == 1  # auto picked the free GPU
    assert body["script_path"] == f"{body['work_dir']}/run.sh"
    assert body["work_dir"].startswith(f"{BASE}/mnist/jobs/train-")
    script = body["script"]
    for line in ["export CUDA_VISIBLE_DEVICES=1", "export SEED=42", "trap on_signal TERM INT HUP",
                 'echo "$$ $(date +%s)" > "$JOB_DIR/pid"', f"source {BASE}/mnist/venvs/torch/bin/activate",
                 "deadline=$(( $(date +%s) + 1800 ))", 'timeout --kill-after=30 "$remaining" bash -c',
                 '"$JOB_DIR/exit_code"']:
        assert line in script, line
    spec = JobSpec(job_name="t", script="x", args=["--epochs", "20", "it's"])
    assert job_command(spec, "python3") == """python3 "$PRE_JOB_DIR/main.py" --epochs 20 'it'"'"'s'"""
    assert f"bash -c {shlex.quote(job_command(spec, 'python'))}" in script
    assert "sbatch" not in script and "SBATCH" not in script
    assert {"'partition' is ignored on the workstation backend",
            "'modules' is ignored on the workstation backend"} <= set(body["warnings"])
    assert client.get(f"/hpc/sessions/{session}/jobs").json() == []
    if shutil.which("bash"):
        subprocess.run(["bash", "-n"], input=script.encode(), check=True)


def test_busy_gpu_is_refused_with_details(client, session):
    r = submit(client, session, gpu=0)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "GPU 0" in detail["message"] and "force=true" in detail["message"]
    assert detail["gpu"]["index"] == 0 and detail["gpu"]["busy"] is True
    assert [g["index"] for g in detail["gpus"]] == [0, 1]

    dry = submit(client, session, gpu=0, dry_run=True).json()
    assert any("will be refused" in w for w in dry["warnings"])
    forced = submit(client, session, gpu=0, force=True)
    assert forced.status_code == 200 and forced.json()["gpu"] == 0
    assert any("launching anyway" in w for w in forced.json()["warnings"])
    assert submit(client, session, gpu=7).status_code == 400


def test_auto_gpu_refused_when_every_gpu_is_busy(client, session):
    assert submit(client, session).json()["gpu"] == 1  # now GPU 1 is busy with our job
    gpus = client.get(f"/hpc/sessions/{session}/gpus").json()["gpus"]
    assert gpus[1]["busy"] and any(p["ours"] for p in gpus[1]["processes"])
    assert submit(client, session).status_code == 409
    cpu = submit(client, session, gpu="none").json()
    assert cpu["gpu"] is None and "export CUDA_VISIBLE_DEVICES=''" in cpu["script"]


def test_workstation_job_lifecycle(client, session):
    job = submit(client, session).json()
    assert job["submitted"] and job["pid"] > 0
    job_id = job["job_id"]
    running = client.get(f"/hpc/sessions/{session}/jobs/{job_id}").json()
    assert running["state"] == "RUNNING" and running["pid"] == job["pid"] and running["gpu"] == 1

    done = wait_for_state(client, session, job_id, {"COMPLETED"})
    assert done["exit_code"] == 0 and done["elapsed"] is not None
    summary = client.get(f"/hpc/sessions/{session}/jobs").json()
    assert [(j["job_id"], j["backend"], j["pid"]) for j in summary] == [(job_id, "workstation", job["pid"])]

    names = {f["name"] for f in client.get(f"/hpc/sessions/{session}/jobs/{job_id}/results").json()}
    assert {"results.csv", "metrics.json", "loss_curve.png", "output.log", "run.sh", "main.py",
            "pid", "exit_code"} <= names
    csv = client.get(f"/hpc/sessions/{session}/jobs/{job_id}/results/results.csv")
    assert csv.headers["content-type"].startswith("text/csv") and csv.text.startswith("epoch,loss,accuracy\n")
    png = client.get(f"/hpc/sessions/{session}/jobs/{job_id}/results/loss_curve.png")
    assert png.content.startswith(b"\x89PNG")
    # GPU is free again once the job ends.
    assert client.get(f"/hpc/sessions/{session}/gpus").json()["gpus"][1]["busy"] is False


def test_parameter_sweep_runs_sequentially(client, session):
    job = submit(client, session, job_name="lr-sweep", args=["--lr", "$LR"],
                 parameters=[{"LR": 0.1}, {"LR": 0.01}, {"LR": 0.001}]).json()
    assert job["array_size"] == 3 and "--array" not in job["script"]
    for i in range(3):
        assert f"mkdir -p {job['work_dir']}/run_{i}" in job["script"]
    status = client.get(f"/hpc/sessions/{session}/jobs/{job['job_id']}").json()
    assert [t["task_id"] for t in status["tasks"]] == ["run_0", "run_1", "run_2"]
    assert [t["state"] for t in status["tasks"]].count("RUNNING") <= 1  # one at a time

    done = wait_for_state(client, session, job["job_id"], {"COMPLETED"})
    assert [t["state"] for t in done["tasks"]] == ["COMPLETED"] * 3
    files = client.get(f"/hpc/sessions/{session}/jobs/{job['job_id']}/results", params={"ext": "csv,json"}).json()
    assert {f["path"].split("/jobs/")[1].split("/", 1)[1] for f in files} == {
        f"run_{i}/{n}" for i in range(3) for n in ("results.csv", "metrics.json")}
    m = client.get(f"/hpc/sessions/{session}/jobs/{job['job_id']}/results/run_1/metrics.json").json()
    assert m["params"] == {"LR": "0.01"}
    log = client.get(f"/hpc/sessions/{session}/jobs/{job['job_id']}/results/output.log").text
    assert log.index("run 1/3") < log.index("run 2/3") < log.index("run 3/3")


def test_cancel_kills_process_group(client, session):
    job = submit(client, session, parameters=[{"LR": 0.1}, {"LR": 0.2}]).json()
    r = client.post(f"/hpc/sessions/{session}/jobs/{job['job_id']}/cancel")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "CANCELLED" and body["exit_code"] == 143
    assert all(t["state"] in ("CANCELLED", "COMPLETED") for t in body["tasks"])
    # Cancelling again is a no-op.
    assert client.post(f"/hpc/sessions/{session}/jobs/{job['job_id']}/cancel").json()["state"] == "CANCELLED"


def test_stream_job_log(client, session):
    job_id = submit(client, session).json()["job_id"]
    messages = read_stream(client, f"/hpc/sessions/{session}/jobs/{job_id}/stream")
    assert messages[0]["type"] == "status" and messages[0]["state"] == "RUNNING"
    assert messages[-1] == {"type": "done", "state": "COMPLETED", "exit_code": 0}
    log = "".join(m["data"] for m in messages if m["type"] == "log")
    assert "CUDA_VISIBLE_DEVICES=1" in log and "epoch 20/20" in log and "exit code 0" in log


def test_unknown_jobs(client, session):
    assert client.get(f"/hpc/sessions/{session}/jobs/nope").status_code == 404
    assert client.get(f"/hpc/sessions/{session}/jobs/12;ls").status_code == 400
    assert client.post(f"/hpc/sessions/{session}/jobs/nope/cancel").status_code == 404
    msgs = read_stream(client, f"/hpc/sessions/{session}/jobs/nope/stream")
    assert msgs == [{"type": "error", "status": 404, "detail": "job nope was not submitted through this session"}]


@pytest.mark.parametrize("override", [
    {"time_limit": "2:00"}, {"time_limit": "00:61:00"}, {"time_limit": "00:00:00"}, {"gpu": -1},
    {"gpu": "all"}, {"venv": "../x"}, {"job_name": "bad name"}, {"parameters": []},
    {"parameters": [{"LR": 0.1}, {"BATCH": 32}]}, {"args": ["a\nb"]}, {"env": {"1BAD": "x"}},
])
def test_job_spec_validation(client, session, override):
    assert submit(client, session, dry_run=True, **override).status_code == 422, override


# ---------- env setup ----------

def test_env_setup_streams_and_creates_venv(client, session):
    r = client.post(f"/hpc/sessions/{session}/env",
                    json={"project": "mnist", "python_version": "3.11.9", "requirements": ["torch", "numpy>=2"]})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in r.text.splitlines()]
    assert events[-1] == {"type": "done", "exit_code": 0, "venv": f"{BASE}/mnist/venvs/default"}
    out = "".join(e["data"] for e in events if e["type"] == "output")
    assert "pyenv install -s 3.11.9" in out and "Successfully installed torch-1.0.0 numpy-1.0.0" in out

    py = client.post(f"/hpc/sessions/{session}/exec",
                     json={"command": "mnist/venvs/default/bin/python --version"}).json()
    assert py["stdout"] == "Python 3.11.9\n" and py["command"].startswith(f"{BASE}/mnist/venvs/default/bin/python")
    pip = client.post(f"/hpc/sessions/{session}/exec", json={"command": "mnist/venvs/default/bin/pip list"}).json()
    assert "torch==1.0.0" in pip["stdout"]


@pytest.mark.parametrize("body", [
    {"requirements": ["--index-url=http://evil"]}, {"requirements": ["torch\nrm"]},
    {"python_version": "3.11; rm"}, {"name": "../x"},
])
def test_env_setup_validation(client, session, body):
    assert client.post(f"/hpc/sessions/{session}/env", json=body).status_code == 422


# ---------- exec allowlist ----------

def test_exec_workstation_allowlist(client, session):
    def run(cmd):
        return client.post(f"/hpc/sessions/{session}/exec", json={"command": cmd})

    assert "NVIDIA RTX A6000" in run("nvidia-smi --query-gpu=index,uuid,name --format=csv").json()["stdout"]
    assert run("nvidia-smi").json()["exit_code"] == 0
    assert run("ps -u abc123").json()["exit_code"] == 0
    assert run("pyenv versions").json()["stdout"].startswith("  system")
    assert run("mkdir -p mnist/data").json()["command"] == f"mkdir -p {BASE}/mnist/data"
    assert run("ls").json()["command"] == f"ls {BASE}"
    assert "data/" in run("ls mnist").json()["stdout"]

    job = submit(client, session).json()
    log = f"mnist/jobs/{job['job_id']}/output.log"
    assert run(f"tail -n 5 {log}").json()["command"] == f"tail -n 5 {BASE}/{log}"
    assert run(f"cat {log}").json()["exit_code"] == 0
    assert run(f"kill -0 {job['pid']}").json()["exit_code"] == 0

    for bad, code in [("cat /etc/passwd", 403), ("ls ../../../etc", 403), ("ls /data/pre/someone-else", 403),
                      ("python train.py", 403), ("pip install torch", 403), ("/usr/bin/python3 -c 1", 403),
                      ("rm -rf mnist", 403), ("docker ps", 403), ("sudo ls", 403), ("module avail", 403),
                      ("sbatch x.sh", 403), ("kill 2211", 403), ("kill -9 -- -2211", 403),
                      ("nvidia-smi -f /tmp/x", 403), ("ls; rm -rf ~", 403), ("cat $HOME/.ssh/id_rsa", 403)]:
        assert run(bad).status_code == code, bad


def test_check_command_unit():
    ws = WorkstationBackend(load_hpc_settings())
    ctx = JobContext(session_id="s", username="u", base_dir="/data/pre/u", our_pids={100, 200})
    assert ws.check_command(["tail", "-n", "20", "a/log"], ctx) == ["tail", "-n", "20", "/data/pre/u/a/log"]
    assert ws.check_command(["kill", "-TERM", "--", "-100"], ctx) == ["kill", "-TERM", "--", "-100"]
    assert ws.check_command(["kill", "-s", "KILL", "200"], ctx)[-1] == "200"
    assert ws.check_command(["p/venvs/v1/bin/pip3", "list"], ctx)[0] == "/data/pre/u/p/venvs/v1/bin/pip3"
    for argv in (["kill", "300"], ["kill", "-9", "1"], ["cat", "/data/pre/u/../x/secret"],
                 ["p/bin/python"], ["ls", "/data/pre/uu"]):
        with pytest.raises(Forbidden):
            ws.check_command(argv, ctx)
    with pytest.raises(InvalidRequest):
        ws.check_command(["kill", "-9"], ctx)


def test_command_and_path_helpers():
    assert parse_user_command("squeue -u abc123 -o '%i %T'") == ["squeue", "-u", "abc123", "-o", "%i %T"]
    for bad in ["ls; rm", "cat $(whoami)", "ls | sh", "a && b", "ls *.csv", "cat ~/.bashrc"]:
        with pytest.raises(Forbidden):
            parse_user_command(bad)
    assert safe_relpath("/a/b/") == "a/b"
    assert safe_relpath("./a") == "a"
    for bad in ["../x", "a/../../b", "a\\b", "a/\x01b"]:
        with pytest.raises(InvalidRequest):
            safe_relpath(bad)


# ---------- files ----------

def test_upload_list_download(client, session):
    base = f"/hpc/sessions/{session}/projects/mnist/files"
    r = client.put(f"{base}/src/train.py", content=b"print('hi')\n")
    assert r.status_code == 200
    assert r.json() == {"path": f"{BASE}/mnist/src/train.py", "size": 12}
    assert [(f["name"], f["is_dir"]) for f in client.get(base).json()["files"]] == [("src", True)]
    assert [f["name"] for f in client.get(base, params={"path": "src"}).json()["files"]] == ["train.py"]
    assert client.get(f"{base}/src/train.py").content == b"print('hi')\n"
    assert client.get(f"{base}/missing.txt").status_code == 404
    assert client.get(base, params={"path": "../../etc"}).status_code == 400
    assert client.get(f"/hpc/sessions/{session}/projects/bad..name!/files").status_code == 422


def test_job_runs_uploaded_script_with_args(client, session):
    client.put(f"/hpc/sessions/{session}/projects/mnist/files/train.py", content=b"print(1)\n")
    job = client.post(f"/hpc/sessions/{session}/jobs",
                      json={"job_name": "t", "project": "mnist", "script_filename": "train.py",
                            "args": ["--lr", "0.1"], "dry_run": True}).json()
    assert """bash -c 'python3 "$PRE_PROJECT_DIR/train.py" --lr 0.1'""" in job["script"]
