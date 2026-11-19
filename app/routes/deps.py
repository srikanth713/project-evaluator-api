"""Shared FastAPI dependencies: optional API-key check and rate limiting."""

from __future__ import annotations

import hmac

from fastapi import Request

from app.config import Settings
from app.services.evaluation_service import EvaluationService
from app.utils.errors import AppError


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_evaluation_service(request: Request) -> EvaluationService:
    return request.app.state.evaluation_service


async def require_api_key(request: Request) -> None:
    """If API_ACCESS_KEY is set, callers must send it in the X-API-Key header."""
    expected = request.app.state.settings.api_access_key
    if not expected:
        return
    provided = request.headers.get("x-api-key", "")
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        raise AppError(401, "UNAUTHORIZED", "A valid X-API-Key header is required.")


async def enforce_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    retry_after = request.app.state.rate_limiter.check(client_ip)
    if retry_after:
        raise AppError(429, "RATE_LIMITED", f"Too many requests. Try again in {retry_after} seconds.")
