from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.config import Settings
from app.routes.deps import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    """Liveness check used by Render and by client apps."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "ai_configured": settings.gemini_configured,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
