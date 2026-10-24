"""PRE AI router. Person 4 mounts this into the main app with:

    from ai.router import router as ai_router
    app.include_router(ai_router)
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from ai.gemini import GeminiError
from ai.review import review_paper
from ai.schemas import ReviewRequest, ReviewResponse

router = APIRouter(prefix="/ai", tags=["ai"])

PLAYGROUND_HTML = Path(__file__).parent / "playground.html"
DEMO_PAPER = Path(__file__).resolve().parents[2] / "samples" / "demo_paper.tex"


@router.get("/health")
def health():
    return {
        "status": "ok",
        "gemini_key_set": bool(os.environ.get("GEMINI_API_KEY")),
        "model": os.environ.get("GEMINI_MODEL"),
    }


@router.get("/playground", response_class=HTMLResponse, include_in_schema=False)
def playground():
    """Local test page for trying the reviewer in a browser."""
    demo = DEMO_PAPER.read_text() if DEMO_PAPER.exists() else ""
    return PLAYGROUND_HTML.read_text().replace("__DEMO_PAPER__", json.dumps(demo))


@router.post("/review", response_model=ReviewResponse)
def review(req: ReviewRequest):
    try:
        return review_paper(req)
    except GeminiError as e:
        raise HTTPException(status_code=502, detail=str(e))
