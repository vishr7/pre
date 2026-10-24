
import os

from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter
import httpx
from fastapi import HTTPException
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

router = APIRouter(prefix="/defend", tags=["Defend"])


@router.get("/health")
def defend_health():
    agent_id = os.getenv("ELEVENLABS_AGENT_ID")

    return {
        "status": "ok",
        "service": "PRE Defend",
        "agent_configured": bool(agent_id),
    }

@router.get("/signed-url")
async def get_signed_url():
    agent_id = os.getenv("ELEVENLABS_AGENT_ID")
    api_key = os.getenv("ELEVENLABS_API_KEY")

    if not agent_id or not api_key:
        raise HTTPException(
            status_code=500,
            detail="ElevenLabs is not configured"
        )

    url = "https://api.elevenlabs.io/v1/convai/conversation/get_signed_url"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                url,
                params={"agent_id": agent_id},
                headers={"xi-api-key": api_key},
                timeout=15.0
            )
            response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(
                status_code=502,
                detail="Could not connect to ElevenLabs"
            )

    return {"signed_url": response.json()["signed_url"]}