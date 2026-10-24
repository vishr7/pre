"""Standalone app for testing the AI router locally, without Person 4's backend.

Run from backend/:
    .venv/bin/uvicorn ai.dev_main:app --reload --port 8001
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from ai.router import router  # noqa: E402

app = FastAPI(title="PRE AI (dev)")
app.include_router(router)
