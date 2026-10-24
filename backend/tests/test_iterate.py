"""End-to-end contract checks for the trusted local Iterate runner."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import iterate


SCRIPT = '''import argparse, json, os
p = argparse.ArgumentParser()
p.add_argument("--x", type=int)
p.add_argument("--out")
a = p.parse_args()
print(json.dumps({"epoch": 0, "score": float(a.x)}), flush=True)
with open(os.path.join(a.out, "metrics.json"), "w") as f:
    json.dump({"score": float(a.x)}, f)
'''


def proposal():
    return iterate.Proposal(script=SCRIPT, space=iterate.Space(
        objective={"metric": "score", "direction": "maximize"},
        params={"x": iterate.Parameter(type="int", low=1, high=3)},
        strategy="grid", n_trials=3, parallel=2, timeout_seconds=10))


def test_preview_approval_and_parallel_trial_records(tmp_path, monkeypatch):
    monkeypatch.setattr(iterate, "ROOT", tmp_path)
    item = proposal()
    async def scenario():
        response = await iterate.start(iterate.StartRequest(**item.model_dump(), approval_digest=iterate.digest(item)))
        await iterate.TASKS[response["id"]]
        return iterate.study_view(response["id"])
    result = asyncio.run(scenario())
    assert result["status"] == "COMPLETED", result["trials"]
    assert len(result["trials"]) == 3
    assert all(t["status"] == "COMPLETED" for t in result["trials"])
    assert result["best"]["metrics"]["score"] == 3.0
    assert len({t["run_dir"] for t in result["trials"]}) == 3
    assert all(t["progress"] and t["seed"] >= 0 and t["script_sha256"] for t in result["trials"])
    assert json.loads((tmp_path / result["id"] / "trial_0" / "metrics.json").read_text())["score"] >= 1


def test_changed_proposal_cannot_start(tmp_path, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(iterate, "ROOT", tmp_path)
    item = proposal()
    request = iterate.StartRequest(**item.model_dump(), approval_digest="wrong")
    try:
        asyncio.run(iterate.start(request))
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("Changed proposal was accepted")


def test_failed_metric_and_branch_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(iterate, "ROOT", tmp_path)
    async def scenario():
        first = proposal()
        parent = await iterate.start(iterate.StartRequest(**first.model_dump(), approval_digest=iterate.digest(first)))
        await iterate.TASKS[parent["id"]]
        bad = iterate.Proposal(script=SCRIPT.replace('"score": float(a.x)}, f)', '"other": float(a.x)}, f)'),
            space=iterate.Space(objective={"metric": "score", "direction": "maximize"},
                params={"x": iterate.Parameter(type="int", low=2, high=3)}, strategy="grid", n_trials=2, parallel=1, timeout_seconds=10),
            parent_study=parent["id"], parent_trial=2)
        child = await iterate.start(iterate.StartRequest(**bad.model_dump(), approval_digest=iterate.digest(bad)))
        await iterate.TASKS[child["id"]]
        return iterate.study_view(child["id"])
    result = asyncio.run(scenario())
    assert result["parent_trial"] == 2
    assert result["parent_params"] == {"x": 3}
    assert result["status"] == "FAILED"
    assert result["trials"][0]["params"] == {"x": 3}
    assert all(row["status"] == "FAILED" for row in result["trials"])
    assert result["best"] is None


def test_remote_trial_uses_hpc_gpu_and_reads_metrics(tmp_path, monkeypatch):
    from hpc.config import load_hpc_settings
    from hpc.mock_backend import MockBackend
    from hpc.models import ConnectRequest
    from hpc.ssh_client import SessionManager
    from hpc.store import InMemoryStore
    from hpc.workstation import WorkstationBackend
    monkeypatch.setattr(iterate, "ROOT", tmp_path)
    for name, value in {"HPC_MOCK":"true", "HPC_MOCK_2FA":"false", "HPC_MOCK_PENDING_SECONDS":"0.1", "HPC_MOCK_RUN_SECONDS":"0.4", "HPC_POLL_INTERVAL":"0.1", "COMPUTE_BACKEND":"workstation"}.items():
        monkeypatch.setenv(name, value)
    settings = load_hpc_settings()
    manager = SessionManager(MockBackend(settings), WorkstationBackend(settings), InMemoryStore(), settings)
    monkeypatch.setattr(iterate, "hpc_manager", lambda: manager)
    async def scenario():
        connected = await manager.connect(ConnectRequest(username="abc123", password="hunter2"))
        item = iterate.Proposal(script=SCRIPT, space=iterate.Space(objective={"metric":"final_accuracy", "direction":"maximize"}, params={"x":iterate.Parameter(type="int",low=1,high=2)}, strategy="random", n_trials=1, parallel=1, timeout_seconds=10), remote=iterate.RemoteConfig(session_id=connected.session_id))
        started = await iterate.start(iterate.StartRequest(**item.model_dump(), approval_digest=iterate.digest(item)))
        await iterate.TASKS[started["id"]]
        result = iterate.study_view(started["id"])
        await manager.close_all()
        return result
    result = asyncio.run(scenario())
    assert result["status"] == "COMPLETED", result["trials"][0]["error"]
    assert result["best"]["metrics"]["final_accuracy"] > 0
    assert result["trials"][0]["slot"] == 1
    assert result["trials"][0]["run_dir"].startswith("/data/pre/")


def test_slurm_trial_uses_same_ask_tell_path(tmp_path, monkeypatch):
    from hpc.config import load_hpc_settings
    from hpc.mock_backend import MockBackend
    from hpc.models import ConnectRequest
    from hpc.ssh_client import SessionManager
    from hpc.slurm import SlurmBackend
    from hpc.store import InMemoryStore
    monkeypatch.setattr(iterate, "ROOT", tmp_path)
    for name, value in {"HPC_MOCK":"true", "HPC_MOCK_2FA":"false", "HPC_MOCK_PENDING_SECONDS":"0.1", "HPC_MOCK_RUN_SECONDS":"0.4", "HPC_POLL_INTERVAL":"0.1", "COMPUTE_BACKEND":"slurm", "JUMP_HOST":""}.items():
        monkeypatch.setenv(name, value)
    settings = load_hpc_settings()
    manager = SessionManager(MockBackend(settings), SlurmBackend(settings), InMemoryStore(), settings)
    monkeypatch.setattr(iterate, "hpc_manager", lambda: manager)
    async def scenario():
        connected = await manager.connect(ConnectRequest(username="abc123", password="hunter2"))
        item = iterate.Proposal(script=SCRIPT, space=iterate.Space(objective={"metric":"final_accuracy", "direction":"maximize"}, params={"x":iterate.Parameter(type="int",low=1,high=2)}, strategy="random", n_trials=1, parallel=1, timeout_seconds=10), remote=iterate.RemoteConfig(session_id=connected.session_id))
        started = await iterate.start(iterate.StartRequest(**item.model_dump(), approval_digest=iterate.digest(item)))
        await iterate.TASKS[started["id"]]
        result = iterate.study_view(started["id"])
        await manager.close_all()
        return result
    result = asyncio.run(scenario())
    assert result["status"] == "COMPLETED", result["trials"][0]["error"]
    assert result["best"]["metrics"]["final_accuracy"] > 0
    assert "pre-projects" in result["trials"][0]["run_dir"]
