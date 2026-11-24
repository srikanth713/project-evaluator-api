"""Pydantic models for requests, AI output and API responses (compact format)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.validators import clean_text, normalize_github_url

MAX_ITEMS = 3          # max improvements returned
MAX_ITEM_CHARS = 200   # max characters per improvement


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    project_title: str = Field(min_length=1, max_length=150)
    project_description: str = Field(min_length=10, max_length=4000)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    github_url: str
    repo_access_consent: bool = Field(
        default=False,
        description="Student's explicit consent to analyse a private repository. "
        "Only honoured when the server has ALLOW_PRIVATE_REPOS=true.",
    )

    @field_validator("project_title", "project_description")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = clean_text(v)
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("technologies")
    @classmethod
    def _clean_technologies(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in v:
            item = clean_text(item)
            if not item:
                continue
            if len(item) > 50:
                raise ValueError("each technology must be 50 characters or fewer")
            if item.lower() not in {c.lower() for c in cleaned}:
                cleaned.append(item)
        return cleaned

    @field_validator("github_url")
    @classmethod
    def _validate_github_url(cls, v: str) -> str:
        return normalize_github_url(v)


# ----------------------------- AI output ----------------------------------


def _clean_str_list(v: Any, limit: int = MAX_ITEMS) -> Any:
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list):
        return v
    out = []
    for item in v:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:MAX_ITEM_CHARS])
    return out[:limit]


class ScoreBreakdown(BaseModel):
    """Internal sub-scores. The API sums them into the single `score` it returns."""

    organization: int = Field(ge=0, le=20)
    implementation: int = Field(ge=0, le=20)
    documentation: int = Field(ge=0, le=20)
    maintainability: int = Field(ge=0, le=20)
    innovation: int = Field(ge=0, le=20)

    @property
    def total(self) -> int:
        return (
            self.organization
            + self.implementation
            + self.documentation
            + self.maintainability
            + self.innovation
        )


class AIAnalysis(BaseModel):
    """The structure Gemini must return. Validated before being trusted."""

    improvements: list[str] = Field(min_length=1)
    score_breakdown: ScoreBreakdown

    @field_validator("improvements", mode="before")
    @classmethod
    def _improvements(cls, v: Any) -> Any:
        return _clean_str_list(v)


# ----------------------------- API response -------------------------------


class EvaluationResponse(BaseModel):
    success: bool = True
    project_id: str
    score: int = Field(ge=0, le=100)
    improvements: list[str]


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict] | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
