
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import dotenv_values
from pathlib import Path
import os

if __package__:
    from .config import get_settings
    from .routes.projects import router as projects_router
    from .routes.defend import router as defend_router
    from .iterate import router as iterate_router
    from .hpc.config import is_hpc_env_name
    from .hpc.router import router as hpc_router, shutdown_hpc
else:  # Support the existing `uvicorn main:app` backend launch.
    from config import get_settings
    from routes.projects import router as projects_router
    from routes.defend import router as defend_router
    from iterate import router as iterate_router
    from hpc.config import is_hpc_env_name
    from hpc.router import router as hpc_router, shutdown_hpc

# Load server configuration without adding credentials to os.environ.
# Each service calls settings.require(...) only when that service is enabled.
get_settings()
for _name, _value in (dotenv_values(Path(__file__).resolve().parents[1] / ".env", interpolate=False) or {}).items():
    if is_hpc_env_name(_name) and _value is not None:
        os.environ.setdefault(_name, _value)

app = FastAPI(title="PRE Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(projects_router)
app.include_router(defend_router)
app.include_router(iterate_router)
app.include_router(hpc_router)

@app.on_event("shutdown")
async def close_hpc_connections():
    await shutdown_hpc()

@app.get("/")
def home():
    return {"message": "PRE Backend is running!"}

@app.get("/health")
def health():
    return {"status": "ok"}
