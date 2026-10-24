"""Shared fixtures: a TestClient wired to the mock transport with fast timings."""

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hpc.config import get_hpc_settings
from hpc.router import get_manager, router

ISOLATED_ENV = ("JUMP_HOST", "TARGET_HOST", "BASE_DIR", "HPC_REMOTE_BASE_DIR", "GPU_BUSY_UTIL_PERCENT",
                "GPU_BUSY_MEMORY_MB", "HPC_ALLOW_KEY_PATHS")


def make_client(monkeypatch, **env) -> TestClient:
    for name in ISOLATED_ENV:
        monkeypatch.delenv(name, raising=False)
    defaults = {"HPC_MOCK": "true", "COMPUTE_BACKEND": "workstation", "HPC_MOCK_PENDING_SECONDS": "0.3",
                "HPC_MOCK_RUN_SECONDS": "0.6", "HPC_POLL_INTERVAL": "0.1", "HPC_MOCK_2FA": "false"}
    for k, v in {**defaults, **env}.items():
        monkeypatch.setenv(k, v)
    get_hpc_settings.cache_clear()
    get_manager.cache_clear()
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_caches():
    yield
    get_hpc_settings.cache_clear()
    get_manager.cache_clear()


def wait_for_state(client, session, job_id, states, timeout=8.0):
    deadline = time.monotonic() + timeout
    body = None
    while time.monotonic() < deadline:
        body = client.get(f"/hpc/sessions/{session}/jobs/{job_id}").json()
        if body["state"] in states:
            return body
        time.sleep(0.05)
    raise AssertionError(f"job never reached {states}, last: {body}")


def read_stream(client, url):
    messages = []
    with client.websocket_connect(url) as ws:
        while True:
            msg = ws.receive_json()
            messages.append(msg)
            if msg["type"] in ("done", "error"):
                return messages
