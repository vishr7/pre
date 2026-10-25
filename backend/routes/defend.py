import httpx
from fastapi import APIRouter, HTTPException, Query

try:
    from ..config import get_settings, ConfigurationError
except ImportError:
    from config import get_settings, ConfigurationError


router = APIRouter(prefix="/defend", tags=["Defend"])


@router.get("/health")
def defend_health():
    settings = get_settings()
    configured = {}
    for examiner, setting_name in (
        ("supportive", "ELEVENLABS_AGENT_ID"),
        ("critical", "ELEVENLABS_CRITICAL_REVIEWER_AGENT_ID"),
    ):
        try:
            settings.require(setting_name)
            configured[examiner] = True
        except ConfigurationError:
            configured[examiner] = False

    return {
        "status": "ok",
        "service": "PRE Defend",
        "agent_configured": configured["supportive"],
        "examiners": configured,
    }

@router.get("/signed-url")
async def get_signed_url(examiner: str = Query(default="supportive", pattern="^(supportive|critical)$")):
    setting_name = (
        "ELEVENLABS_AGENT_ID"
        if examiner == "supportive"
        else "ELEVENLABS_CRITICAL_REVIEWER_AGENT_ID"
    )
    try:
        settings = get_settings()
        agent_id = settings.require(setting_name).get_secret_value()
    except ConfigurationError:
        label = "Supportive Professor" if examiner == "supportive" else "Critical Reviewer"
        raise HTTPException(
            status_code=503,
            detail=f"{label} is not configured on the backend",
        )
    try:
        settings = get_settings()
        api_key = settings.require("ELEVENLABS_API_KEY").get_secret_value()
    except ConfigurationError:
        raise HTTPException(
            status_code=503,
            detail="ElevenLabs API access is not configured on the backend",
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
