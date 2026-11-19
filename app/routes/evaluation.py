from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Depends

from app.config import Settings
from app.routes.deps import enforce_rate_limit, get_evaluation_service, get_settings, require_api_key
from app.schemas.project import ErrorResponse, EvaluationRequest, EvaluationResponse
from app.services.evaluation_service import EvaluationService
from app.utils.errors import AppError

router = APIRouter(prefix="/projects", tags=["projects"])

_ERRORS = {
    401: {"model": ErrorResponse, "description": "Missing or invalid X-API-Key"},
    403: {"model": ErrorResponse, "description": "Private or inaccessible repository"},
    404: {"model": ErrorResponse, "description": "Repository not found"},
    422: {"model": ErrorResponse, "description": "Invalid request or empty repository"},
    429: {"model": ErrorResponse, "description": "Rate limited (this API, GitHub or Gemini)"},
    502: {"model": ErrorResponse, "description": "Upstream (GitHub/Gemini) error or invalid AI output"},
    503: {"model": ErrorResponse, "description": "AI service not configured"},
    504: {"model": ErrorResponse, "description": "Upstream timeout"},
}


@router.post(
    "/evaluate",
    response_model=EvaluationResponse,
    responses=_ERRORS,
    dependencies=[Depends(require_api_key), Depends(enforce_rate_limit)],
)
async def evaluate_project(
    payload: EvaluationRequest,
    service: EvaluationService = Depends(get_evaluation_service),
    settings: Settings = Depends(get_settings),
) -> EvaluationResponse:
    """Analyse a student project and its public GitHub repository."""
    try:
        return await asyncio.wait_for(service.evaluate(payload), timeout=settings.overall_timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise AppError(504, "REQUEST_TIMEOUT", "The evaluation took too long. Please try again.") from exc


@router.get(
    "/{project_id}/result",
    response_model=EvaluationResponse,
    responses={k: v for k, v in _ERRORS.items() if k in (401, 404, 422)},
    dependencies=[Depends(require_api_key)],
)
async def get_result(
    project_id: str,
    service: EvaluationService = Depends(get_evaluation_service),
) -> EvaluationResponse:
    """Retrieve a previously saved evaluation by the `project_id` returned from /evaluate."""
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", project_id):
        raise AppError(422, "INVALID_PROJECT_ID", "project_id must be a UUID.")
    return await service.get_result(project_id.lower())
