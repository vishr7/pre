import httpx
from fastapi import APIRouter, HTTPException

try:
    from ..config import get_settings, ConfigurationError
except ImportError:
    from config import get_settings, ConfigurationError


router = APIRouter(prefix="/defend", tags=["Defend"])


@router.get("/health")
def defend_health():
    settings = get_settings()

    try:
        settings.require("ELEVENLABS_AGENT_ID")
        configured = True
    except ConfigurationError:
        configured = False

    return {
        "status": "ok",
        "service": "PRE Defend",
        "agent_configured": configured,
    }

@router.get("/signed-url")
async def get_signed_url():
    try:
        settings = get_settings()
        agent_id = settings.require("ELEVENLABS_AGENT_ID").get_secret_value()
        api_key = settings.require("ELEVENLABS_API_KEY").get_secret_value()
    except ConfigurationError:
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
