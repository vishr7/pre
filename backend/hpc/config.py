"""HPC module settings, read from environment variables (none of these are secrets)."""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

WORKSTATION_JUMP_HOST = "ssh.ist.psu.edu"
WORKSTATION_TARGET_HOST = "nittanyaicompute.ist.psu.edu"
SLURM_TARGET_HOST = "submit.hpc.psu.edu"
# Non-HPC_-prefixed variables this module reads (main.py exports only these from .env).
EXTRA_ENV_NAMES = {"COMPUTE_BACKEND", "JUMP_HOST", "TARGET_HOST", "BASE_DIR",
                   "GPU_BUSY_UTIL_PERCENT", "GPU_BUSY_MEMORY_MB"}


def is_hpc_env_name(name: str) -> bool:
    return name.startswith("HPC_") or name in EXTRA_ENV_NAMES


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value and value.strip() else default


@dataclass(frozen=True)
class HPCSettings:
    mock: bool
    compute_backend: Literal["workstation", "slurm"]
    target_host: str              # default host for /hpc/connect
    jump_host: str | None         # default jump host ("" in env disables it)
    base_dir: str                 # workstation: jobs live in <base_dir>/<username>/<project>
    remote_base_dir: str          # slurm: relative paths resolve against the remote $HOME
    connect_timeout: float        # seconds to wait for connect / each 2FA round
    auth_timeout: float           # seconds the SSH handshake waits for a 2FA answer
    keepalive_interval: float
    strict_host_keys: bool
    known_hosts: str | None
    allow_key_paths: bool         # allow reading private keys from this server's disk
    exec_max_timeout: float
    env_timeout: float            # venv creation + pip install
    max_download_bytes: int
    poll_interval: float          # WebSocket status/log poll period
    gpu_busy_util_percent: float
    gpu_busy_memory_mb: float
    mock_pending_seconds: float
    mock_run_seconds: float
    mock_2fa: bool


def load_hpc_settings() -> HPCSettings:
    backend = (os.environ.get("COMPUTE_BACKEND") or "workstation").strip().lower()
    if backend not in ("workstation", "slurm"):
        raise ValueError("COMPUTE_BACKEND must be 'workstation' or 'slurm'")
    workstation = backend == "workstation"
    jump = os.environ.get("JUMP_HOST")
    return HPCSettings(
        mock=_bool("HPC_MOCK", False),
        compute_backend=backend,
        target_host=os.environ.get("TARGET_HOST") or (WORKSTATION_TARGET_HOST if workstation else SLURM_TARGET_HOST),
        jump_host=(jump.strip() or None) if jump is not None else (WORKSTATION_JUMP_HOST if workstation else None),
        base_dir=(os.environ.get("BASE_DIR") or "/data/pre").rstrip("/"),
        remote_base_dir=os.environ.get("HPC_REMOTE_BASE_DIR") or "pre-projects",
        connect_timeout=_float("HPC_CONNECT_TIMEOUT", 60),
        auth_timeout=_float("HPC_AUTH_TIMEOUT", 180),
        keepalive_interval=_float("HPC_KEEPALIVE_INTERVAL", 30),
        strict_host_keys=_bool("HPC_STRICT_HOST_KEYS", True),
        known_hosts=os.environ.get("HPC_KNOWN_HOSTS") or None,
        allow_key_paths=_bool("HPC_ALLOW_KEY_PATHS", False),
        exec_max_timeout=_float("HPC_EXEC_MAX_TIMEOUT", 300),
        env_timeout=_float("HPC_ENV_TIMEOUT", 1800),
        max_download_bytes=int(_float("HPC_MAX_DOWNLOAD_MB", 100) * 1024 * 1024),
        poll_interval=_float("HPC_POLL_INTERVAL", 5),
        gpu_busy_util_percent=_float("GPU_BUSY_UTIL_PERCENT", 10),
        gpu_busy_memory_mb=_float("GPU_BUSY_MEMORY_MB", 1024),
        mock_pending_seconds=_float("HPC_MOCK_PENDING_SECONDS", 8),
        mock_run_seconds=_float("HPC_MOCK_RUN_SECONDS", 22),
        mock_2fa=_bool("HPC_MOCK_2FA", True),
    )


@lru_cache(maxsize=1)
def get_hpc_settings() -> HPCSettings:
    return load_hpc_settings()
