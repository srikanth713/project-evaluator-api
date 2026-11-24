"""Orchestrates GitHub retrieval, Gemini analysis, score assembly and persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.schemas.project import EvaluationRequest, EvaluationResponse
from app.services.gemini_service import GeminiService
from app.services.github_service import GitHubService
from app.services.storage import EvaluationStore
from app.utils.errors import AppError
from app.utils.validators import parse_github_url


class EvaluationService:
    def __init__(
        self,
        settings: Settings,
        github: GitHubService,
        gemini: GeminiService,
        store: EvaluationStore,
    ) -> None:
        self._settings = settings
        self._github = github
        self._gemini = gemini
        self._store = store

    async def evaluate(self, request: EvaluationRequest) -> EvaluationResponse:
        # Fail fast (before any GitHub traffic) if the AI cannot be used.
        if not self._gemini.configured:
            raise AppError(
                503,
                "AI_NOT_CONFIGURED",
                "The AI service is not configured on the server (missing GEMINI_API_KEY).",
            )

        owner, repo = parse_github_url(request.github_url)
        snapshot = await self._github.fetch_repository(owner, repo, private_consent=request.repo_access_consent)
        ai = await self._gemini.analyze(request, snapshot)

        response = EvaluationResponse(
            project_id=str(uuid.uuid4()),
            # Always computed server-side from the five 0-20 sub-scores (never trusted from the AI).
            score=ai.score_breakdown.total,
            improvements=ai.improvements,
        )
        await self._store.save(
            response.project_id,
            request.student_id,
            datetime.now(timezone.utc).isoformat(),
            response.model_dump_json(),
        )
        return response

    async def get_result(self, project_id: str) -> EvaluationResponse:
        payload = await self._store.get(project_id)
        if payload is None:
            raise AppError(404, "RESULT_NOT_FOUND", "No saved evaluation was found for this project id.")
        return EvaluationResponse.model_validate_json(payload)
