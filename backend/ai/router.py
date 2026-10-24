"""PRE AI router. Person 4 mounts this into the main app with:

    from ai.router import router as ai_router
    app.include_router(ai_router)
"""

import os

from fastapi import APIRouter

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "gemini_key_set": bool(os.environ.get("GEMINI_API_KEY")),
        "model": os.environ.get("GEMINI_MODEL"),
    }
