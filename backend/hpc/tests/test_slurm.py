"""SLURM backend (COMPUTE_BACKEND=slurm) against the mock machine, plus pure parsing tests."""

import pytest

from hpc import slurm
from hpc.backend import InvalidRequest, NotFound, SlurmError
from hpc.models import JobSpec, JobState

from .conftest import make_client, read_stream, wait_for_state

CREDS = {"username": "abc123", "password": "hunter2"}


@pytest.fixture
def client(monkeypatch):
    with make_client(monkeypatch, COMPUTE_BACKEND="slurm") as c:
        yield c


@pytest.fixture
def session(client):
    r = client.post("/hpc/connect", json=CREDS)
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


SPEC = {"job_name": "train-mnist", "project": "mnist", "command": "python main.py",
        "script": "print('training')\n", "partition": "open", "account": "abc123_lab",
        "cpus_per_task": 4, "memory": "16G", "gpus": 1, "time_limit": "02:00:00",
        "modules": ["anaconda/2023.09", "cuda/12.1"], "conda_env": "pre", "env": {"SEED": "42"}}


def test_slurm_session_defaults(client, session):
    status = client.get(f"/hpc/sessions/{session}/status").json()
    assert status["host"] == "submit.hpc.psu.edu" and status["jump_host"] is None
    assert status["backend"] == "slurm"
    assert status["base_dir"] == "/storage/home/abc123/pre-projects"
    assert client.get(f"/hpc/sessions/{session}/gpus").status_code == 501


def test_exec_slurm_allowlist(client, session):
    r = client.post(f"/hpc/sessions/{session}/exec", json={"command": "mkdir -p pre-projects/demo"})
    assert r.status_code == 200 and r.json()["exit_code"] == 0
    assert "pre-projects/" in client.post(f"/hpc/sessions/{session}/exec", json={"command": "ls"}).json()["stdout"]
    assert "pytorch" in client.post(f"/hpc/sessions/{session}/exec",
                                    json={"command": "module avail"}).json()["stderr"]
    for bad in ["rm -rf ~", "nvidia-smi", "ls; rm -rf ~", "squeue && reboot"]:
        assert client.post(f"/hpc/sessions/{session}/exec", json={"command": bad}).status_code == 403, bad


def test_dry_run_generates_sbatch(client, session):
    r = client.post(f"/hpc/sessions/{session}/jobs", json={**SPEC, "dry_run": True, "venv": "x"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submitted"] is False and body["job_id"] is None and body["backend"] == "slurm"
    script = body["script"]
    for line in ["#SBATCH --job-name=train-mnist", "#SBATCH --partition=open",
                 "#SBATCH --account=abc123_lab", "#SBATCH --cpus-per-task=4", "#SBATCH --mem=16G",
                 "#SBATCH --gres=gpu:1", "#SBATCH --time=02:00:00", "module load cuda/12.1",
                 "conda activate pre", "export SEED=42", "python main.py"]:
        assert line in script, line
    assert f"#SBATCH --chdir={body['work_dir']}" in script and "--array" not in script
    assert body["warnings"] == ["'venv' is ignored on the slurm backend"]
    assert client.get(f"/hpc/sessions/{session}/jobs").json() == []


@pytest.mark.parametrize("override", [
    {"cpus_per_task": 0}, {"nodes": -1}, {"gpus": -1}, {"memory": "0G"}, {"memory": "lots"},
    {"partition": "open; rm -rf ~"}, {"modules": ["x && y"]},
])
def test_slurm_spec_validation(client, session, override):
    r = client.post(f"/hpc/sessions/{session}/jobs", json={**SPEC, **override, "dry_run": True})
    assert r.status_code == 422, override


def test_submit_monitor_results(client, session):
    job = client.post(f"/hpc/sessions/{session}/jobs", json=SPEC).json()
    assert job["submitted"] is True and job["job_id"].isdigit()
    job_id = job["job_id"]
    assert client.get(f"/hpc/sessions/{session}/jobs/{job_id}").json()["state"] in ("PENDING", "RUNNING")
    done = wait_for_state(client, session, job_id, {"COMPLETED"})
    assert done["exit_code"] == 0 and done["work_dir"] == job["work_dir"]

    names = {f["name"] for f in client.get(f"/hpc/sessions/{session}/jobs/{job_id}/results").json()}
    assert {"results.csv", "metrics.json", "loss_curve.png", "job.sbatch", "main.py",
            f"slurm-{job_id}.out"} <= names
    csv = client.get(f"/hpc/sessions/{session}/jobs/{job_id}/results/results.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.startswith("epoch,loss,accuracy\n1,")


def test_parameter_sweep_job_array(client, session):
    spec = {**SPEC, "job_name": "lr-sweep", "command": "python main.py --lr $LR",
            "parameters": [{"LR": 0.1}, {"LR": 0.01}, {"LR": 0.001}], "max_concurrent": 2}
    job = client.post(f"/hpc/sessions/{session}/jobs", json=spec).json()
    assert job["array_size"] == 3
    assert "#SBATCH --array=0-2%2" in job["script"]
    assert "LR_VALUES=( 0.1 0.01 0.001 )" in job["script"]
    assert 'export LR="${LR_VALUES[$SLURM_ARRAY_TASK_ID]}"' in job["script"]

    done = wait_for_state(client, session, job["job_id"], {"COMPLETED"})
    assert [t["task_id"] for t in done["tasks"]] == [f"{job['job_id']}_{i}" for i in range(3)]
    metrics = client.get(f"/hpc/sessions/{session}/jobs/{job['job_id']}/results/metrics_task1.json").json()
    assert metrics["params"] == {"LR": "0.01"}


def test_cancel_and_errors(client, session):
    job_id = client.post(f"/hpc/sessions/{session}/jobs", json=SPEC).json()["job_id"]
    r = client.post(f"/hpc/sessions/{session}/jobs/{job_id}/cancel")
    assert r.json()["state"] == "CANCELLED" and r.json()["exit_code"] == 128 + 15

    r = client.post(f"/hpc/sessions/{session}/jobs", json={**SPEC, "partition": "nonexistent"})
    assert r.status_code == 422 and "invalid partition" in r.json()["detail"]
    assert client.get(f"/hpc/sessions/{session}/jobs/999999").status_code == 404
    assert client.get(f"/hpc/sessions/{session}/jobs/999999/results").status_code == 404


def test_stream_slurm_log(client, session):
    job_id = client.post(f"/hpc/sessions/{session}/jobs", json=SPEC).json()["job_id"]
    messages = read_stream(client, f"/hpc/sessions/{session}/jobs/{job_id}/stream")
    states = [m["state"] for m in messages if m["type"] == "status"]
    assert messages[-1]["state"] == "COMPLETED" and len(set(states)) >= 2
    log = "".join(m["data"] for m in messages if m["type"] == "log")
    assert "epoch 20/20" in log and log.rstrip().endswith("finished")


def test_slurm_parsing():
    assert slurm.parse_sbatch_output("4815162\n", "", 0) == "4815162"
    assert slurm.parse_sbatch_output("77;roar\n", "", 0) == "77"
    with pytest.raises(SlurmError):
        slurm.parse_sbatch_output("", "sbatch: error: Batch job submission failed", 1)

    tasks = slurm.parse_sacct("12_0|COMPLETED|00:01:00|0:0\n12_1|CANCELLED by 999|00:00:30|0:15\n"
                              "12_2|TIMEOUT|02:00:00|0:0\n")
    assert [t.state for t in tasks] == [JobState.COMPLETED, JobState.CANCELLED, JobState.FAILED]
    assert [t.exit_code for t in tasks] == [0, 143, 0]
    status = slurm.aggregate_status("12", tasks)
    assert status.state == JobState.FAILED and status.elapsed == "02:00:00" and status.exit_code == 143

    live = slurm.parse_squeue("12_3|RUNNING|5:01|None\n")
    merged = slurm.merge_tasks(live, slurm.parse_sacct("12_[3-4]|PENDING|00:00:00|0:0\n12_0|COMPLETED|00:01:00|0:0\n"))
    assert [t.task_id for t in merged] == ["12_0", "12_3"]
    assert slurm.aggregate_status("12", merged).state == JobState.RUNNING
    assert slurm.parse_squeue("13|PENDING|0:00|Priority\n")[0].reason == "Priority"

    with pytest.raises(NotFound):
        slurm.aggregate_status("1", [])
    with pytest.raises(InvalidRequest):
        slurm.squeue_command("1 && rm")


def test_render_rejects_whitespace_work_dir():
    with pytest.raises(InvalidRequest):
        slurm.render_sbatch(JobSpec(job_name="x", command="true"), "/home/a b/x", "/home/a b")
