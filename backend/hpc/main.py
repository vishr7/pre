"""Standalone app for testing the HPC router locally.

Run from backend/:
    .venv/Scripts/uvicorn hpc.main:app --reload --port 8002      (Windows)
    .venv/bin/uvicorn hpc.main:app --reload --port 8002          (macOS/Linux)
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import dotenv_values
from fastapi import FastAPI

from hpc.config import is_hpc_env_name

# Only export this module's settings; other .env values (API keys) must not enter os.environ.
_env_file = Path(__file__).resolve().parents[2] / ".env"
for _name, _value in (dotenv_values(_env_file, interpolate=False) if _env_file.is_file() else {}).items():
    if is_hpc_env_name(_name) and _value is not None:
        os.environ.setdefault(_name, _value)

from hpc.router import router, shutdown_hpc  # noqa: E402

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await shutdown_hpc()


app = FastAPI(title="PRE HPC (dev)", lifespan=lifespan)
app.include_router(router)


@app.get("/", include_in_schema=False)
def root():
    return {"docs": "/docs", "health": "/hpc/health"}
