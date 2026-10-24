"""Pydantic request/response models for the /hpc API."""

import re
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

NAME_RE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
SLURM_TOKEN_RE = r"^[A-Za-z0-9_.:+-]{1,64}$"
MODULE_RE = r"^[A-Za-z0-9_./+-]{1,128}$"
ENV_NAME_RE = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
JOB_ID_RE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"  # slurm "123" / "123_4", workstation dir name
TIME_RE = re.compile(r"^(\d{1,3}):([0-5]\d):([0-5]\d)$")


# ---------- connection ----------

class ConnectRequest(BaseModel):
    """Credentials are SecretStr so they never show up in reprs or logs."""

    host: str | None = Field(None, max_length=255, description="Defaults to TARGET_HOST",
                             examples=["nittanyaicompute.ist.psu.edu"])
    port: int = Field(22, ge=1, le=65535)
    jump_host: str | None = Field(None, max_length=255,
                                  description='Defaults to JUMP_HOST; "" connects directly')
    jump_port: int = Field(22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: SecretStr | None = None
    private_key: SecretStr | None = Field(None, description="PEM/OpenSSH private key contents")
    private_key_path: str | None = Field(None, description="Path on the PRE server (if enabled)")
    passphrase: SecretStr | None = None

    @model_validator(mode="after")
    def _one_credential(self):
        if not (self.password or self.private_key or self.private_key_path):
            raise ValueError("provide a password, private_key, or private_key_path")
        if self.private_key and self.private_key_path:
            raise ValueError("provide private_key or private_key_path, not both")
        return self


class AuthPrompt(BaseModel):
    prompt: str
    echo: bool  # False means the answer should be hidden (e.g. a password field)


SessionState = Literal["connecting", "awaiting_2fa", "connected", "disconnected", "failed"]


class ConnectResponse(BaseModel):
    session_id: str
    status: SessionState
    hop: str | None = Field(None, description="Host asking the prompts (jump host or target)")
    instructions: str | None = None
    prompts: list[AuthPrompt] = []


class RespondRequest(BaseModel):
    responses: list[SecretStr] = Field(description="One answer per prompt, in order")


class SessionStatus(BaseModel):
    session_id: str
    host: str
    port: int
    username: str
    jump_host: str | None = None
    status: SessionState
    mock: bool
    backend: str
    created_at: datetime
    connected_at: datetime | None = None
    base_dir: str | None = None
    error: str | None = None
    hop: str | None = None
    prompts: list[AuthPrompt] = []


# ---------- exec / files ----------

class ExecRequest(BaseModel):
    command: str = Field(min_length=1, max_length=4096, examples=["squeue -u abc123"])
    timeout: float = Field(30, gt=0, le=600)


class ExecResponse(BaseModel):
    command: str
    stdout: str
    stderr: str
    exit_code: int | None


class FileInfo(BaseModel):
    name: str
    path: str
    size: int
    is_dir: bool
    modified: datetime | None = None


class FileListResponse(BaseModel):
    path: str
    files: list[FileInfo]


class UploadResponse(BaseModel):
    path: str
    size: int


# ---------- SLURM jobs ----------

Scalar = str | int | float


class JobSpec(BaseModel):
    """One spec for both backends. SLURM-only fields are ignored (with a warning) on the
    workstation; workstation-only fields (gpu, venv, force) are ignored on SLURM."""

    job_name: str = Field(pattern=NAME_RE, examples=["train-mnist"])
    project: str = Field("default", pattern=NAME_RE, description="Per-project working dir")
    command: str | None = Field(
        None, min_length=1, max_length=8192, examples=["python train.py --lr $LR"],
        description="Shell command to run. Default: python <script_filename> <args>",
    )
    script: str | None = Field(None, description="Optional script contents uploaded next to the job")
    script_filename: str = Field("main.py", pattern=NAME_RE,
                                 description="Uploaded with `script`, else a file already in the project dir")
    args: list[str] = Field([], description="Arguments appended to the command (shell-quoted)")
    # workstation
    gpu: int | Literal["auto", "none"] = Field(
        "auto", description='GPU index (sets CUDA_VISIBLE_DEVICES), "auto" = least-loaded free GPU, "none" = CPU')
    venv: str | None = Field(None, pattern=NAME_RE, description="Venv created by POST /env")
    force: bool = Field(False, description="Launch even if the GPU is busy")
    # slurm
    partition: str | None = Field(None, pattern=SLURM_TOKEN_RE)
    account: str | None = Field(None, pattern=SLURM_TOKEN_RE, description="Allocation, e.g. open")
    nodes: int = Field(1, ge=1, le=1024)
    ntasks: int = Field(1, ge=1, le=65536)
    cpus_per_task: int = Field(1, ge=1, le=1024)
    memory: str = Field("4G", pattern=r"^[1-9]\d{0,6}[KMGT]?$", description="e.g. 512M, 16G")
    gpus: int = Field(0, ge=0, le=64)
    time_limit: str = Field("01:00:00", description="HH:MM:SS")
    modules: list[str] = []
    conda_env: str | None = Field(None, pattern=r"^[A-Za-z0-9_./-]{1,128}$")
    env: dict[str, str] = Field({}, description="Extra environment variables")
    parameters: list[dict[str, Scalar]] | None = Field(
        None, description="Parameter variations; submitted as a job array, one task each",
        examples=[[{"LR": 0.1}, {"LR": 0.01}, {"LR": 0.001}]],
    )
    max_concurrent: int | None = Field(None, ge=1, description="Array throttle (%N)")
    dry_run: bool = False

    @field_validator("time_limit")
    @classmethod
    def _time(cls, v: str) -> str:
        m = TIME_RE.match(v)
        if not m:
            raise ValueError("time_limit must be HH:MM:SS")
        if not any(int(x) for x in m.groups()):
            raise ValueError("time_limit must be positive")
        return v

    @field_validator("gpu")
    @classmethod
    def _gpu(cls, v):
        if isinstance(v, int) and not 0 <= v <= 64:
            raise ValueError("gpu index must be between 0 and 64")
        return v

    @field_validator("args")
    @classmethod
    def _args(cls, v: list[str]) -> list[str]:
        if any("\x00" in a or "\n" in a for a in v):
            raise ValueError("arguments must not contain newlines or NUL")
        return v

    def time_limit_seconds(self) -> int:
        h, m, s = (int(x) for x in TIME_RE.match(self.time_limit).groups())
        return h * 3600 + m * 60 + s

    @field_validator("modules")
    @classmethod
    def _modules(cls, v: list[str]) -> list[str]:
        for name in v:
            if not re.match(MODULE_RE, name):
                raise ValueError(f"invalid module name: {name!r}")
        return v

    @field_validator("env")
    @classmethod
    def _env(cls, v: dict[str, str]) -> dict[str, str]:
        for name in v:
            if not re.match(ENV_NAME_RE, name):
                raise ValueError(f"invalid environment variable name: {name!r}")
        return v

    @field_validator("parameters")
    @classmethod
    def _params(cls, v: list[dict[str, Scalar]] | None):
        if v is None:
            return v
        if not v:
            raise ValueError("parameters must contain at least one variation")
        if len(v) > 1000:
            raise ValueError("at most 1000 parameter variations")
        keys = set(v[0])
        if not keys:
            raise ValueError("each variation needs at least one parameter")
        for variation in v:
            if set(variation) != keys:
                raise ValueError("every variation must define the same parameter names")
        for name in keys:
            if not re.match(ENV_NAME_RE, name):
                raise ValueError(f"invalid parameter name: {name!r}")
        return v


class JobSubmitResponse(BaseModel):
    job_id: str | None  # None on dry_run
    submitted: bool
    backend: str
    script: str = Field(description="sbatch script (slurm) or wrapper script (workstation)")
    script_path: str
    work_dir: str
    array_size: int | None = Field(None, description="Number of parameter variations")
    pid: int | None = None
    gpu: int | None = None
    warnings: list[str] = []


class JobState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class JobTask(BaseModel):
    task_id: str
    state: JobState
    raw_state: str
    elapsed: str | None = None
    exit_code: int | None = None
    reason: str | None = None


class JobStatus(BaseModel):
    job_id: str
    state: JobState
    elapsed: str | None = None
    exit_code: int | None = None
    tasks: list[JobTask] = Field([], description="Array tasks (slurm) or sequential runs (workstation)")
    work_dir: str | None = None
    pid: int | None = None
    gpu: int | None = None


class JobSummary(BaseModel):
    job_id: str
    job_name: str
    project: str
    backend: str
    work_dir: str
    array_size: int | None
    pid: int | None = None
    gpu: int | None = None
    submitted_at: datetime


class ResultFile(FileInfo):
    kind: str  # file extension, e.g. "csv"


# ---------- workstation: GPUs and environments ----------

class GPUProcess(BaseModel):
    pid: int | None
    used_memory_mb: int | None
    ours: bool = Field(description="Started by a PRE job in this session")


class GPUInfo(BaseModel):
    index: int
    uuid: str | None
    name: str
    memory_used_mb: int | None
    memory_total_mb: int | None
    utilization_percent: int | None
    busy: bool
    busy_reasons: list[str] = []
    processes: list[GPUProcess] = []


class GPUList(BaseModel):
    gpus: list[GPUInfo]
    busy_util_percent: float
    busy_memory_mb: float


class EnvSetupRequest(BaseModel):
    project: str = Field("default", pattern=NAME_RE)
    name: str = Field("default", pattern=NAME_RE, description="Venv name; use it as JobSpec.venv")
    python_version: str | None = Field(None, pattern=r"^[0-9][0-9A-Za-z._-]{0,31}$",
                                       description="pyenv version, e.g. 3.11.9 (installed if missing)")
    requirements: list[str] = Field([], max_length=200, examples=[["torch", "numpy>=2"]])

    @field_validator("requirements")
    @classmethod
    def _reqs(cls, v: list[str]) -> list[str]:
        for r in v:
            if not r.strip() or r.lstrip().startswith("-") or any(c in r for c in "\n\r\x00"):
                raise ValueError(f"invalid requirement: {r!r} (pip options are not allowed)")
        return v
