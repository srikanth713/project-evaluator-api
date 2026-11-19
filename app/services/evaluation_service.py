"""Orchestrates GitHub retrieval, Gemini analysis, score assembly and persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.config import Settings
from app.schemas.project import (
    EvaluationRequest,
    EvaluationResponse,
    MentorRequirements,
    ProjectAnalysis,
    RepositoryInfo,
    Score,
)
from app.services.gemini_service import GeminiService
from app.services.github_service import GitHubService, RepositorySnapshot
from app.services.storage import EvaluationStore
from app.utils.errors import AppError
from app.utils.validators import parse_github_url

SCORE_CRITERIA = {
    "organization": "Project structure, separation of concerns, dependency/config management (0-20).",
    "implementation": "Apparent technical quality, error handling and use of suitable techniques (0-20).",
    "documentation": "README completeness, setup/usage instructions, comments and docs (0-20).",
    "maintainability": "Readability, modularity, tests, naming and repository hygiene (0-20).",
    "innovation": "Originality and ambition relative to a typical student project (0-20).",
}

SCORE_LIMITATIONS = (
    "This score is an AI-generated estimate based only on the student's description and a limited sample of "
    "public repository files. It does not prove that the code is correct, bug-free or secure, and it was not "
    "produced by running the project or its tests. Use it as guidance, not as a grade."
)

DISCLAIMER = (
    "AI-generated feedback. Repository code was read through the GitHub API only and was never executed."
)


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

        breakdown = ai.score_breakdown
        analysis = ProjectAnalysis(
            project_title=request.project_title,
            detected_domain=ai.detected_domain,
            technologies_identified=ai.technologies_identified,
            programming_languages=ai.programming_languages or list(snapshot.languages.keys())[:6],
            strengths=ai.strengths,
            weaknesses=ai.weaknesses,
            improvement_suggestions=ai.improvement_suggestions,
            documentation_feedback=ai.documentation_feedback,
            architecture_suggestions=ai.architecture_suggestions,
            security_concerns=ai.security_concerns,
            next_steps=ai.next_steps,
            additional_features=ai.additional_features,
            score=Score(
                total=breakdown.total,  # always computed server-side so the breakdown sums to the total
                breakdown=breakdown,
                explanation=ai.score_explanation,
                criteria=SCORE_CRITERIA,
                limitations=SCORE_LIMITATIONS,
            ),
            mentor_requirements=MentorRequirements(
                domain=ai.mentor_requirements.domain,
                required_skills=ai.mentor_requirements.required_skills,
                recommended_mentor_profile=ai.mentor_requirements.recommended_mentor_profile
                or f"Alumni working in {ai.mentor_requirements.domain}.",
            ),
        )

        response = EvaluationResponse(
            project_id=str(uuid.uuid4()),
            student_id=request.student_id,
            evaluated_at=datetime.now(timezone.utc),
            project_analysis=analysis,
            repository=self._repository_info(snapshot),
            disclaimer=DISCLAIMER,
        )
        await self._store.save(
            response.project_id,
            response.student_id,
            response.evaluated_at.isoformat(),
            response.model_dump_json(),
        )
        return response

    async def get_result(self, project_id: str) -> EvaluationResponse:
        payload = await self._store.get(project_id)
        if payload is None:
            raise AppError(404, "RESULT_NOT_FOUND", "No saved evaluation was found for this project id.")
        return EvaluationResponse.model_validate_json(payload)

    @staticmethod
    def _repository_info(snap: RepositorySnapshot) -> RepositoryInfo:
        return RepositoryInfo(
            full_name=snap.full_name,
            url=snap.html_url,
            default_branch=snap.default_branch,
            primary_language=snap.primary_language,
            languages=snap.languages,
            stars=snap.stars,
            last_pushed_at=snap.last_pushed_at,
            has_readme=snap.has_readme,
            has_tests=snap.has_tests,
            has_license=snap.has_license,
            total_files=snap.total_files,
            files_analyzed=list(snap.files.keys()),
            tree_truncated=snap.tree_truncated,
        )
