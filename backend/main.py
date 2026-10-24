from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
if __package__:
    from .config import get_settings
else:  # Support the existing `uvicorn main:app` backend launch.
    from config import get_settings

# Load server configuration without adding credentials to os.environ.
# Each service calls settings.require(...) only when that service is enabled.
get_settings()

app = FastAPI(title="PRE Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def home():
    return {"message": "PRE Backend is running!"}

@app.get("/health")
def health():
    return {"status": "ok"}
