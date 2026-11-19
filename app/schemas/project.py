"""Pydantic models for requests, AI output and API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.validators import clean_text, normalize_github_url

MAX_LIST_ITEMS = 10
MAX_ITEM_CHARS = 600


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


def _clean_str_list(v: Any) -> Any:
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
    return out[:MAX_LIST_ITEMS]


class ScoreBreakdown(BaseModel):
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


class AIMentorRequirements(BaseModel):
    domain: str = Field(min_length=1, max_length=100)
    required_skills: list[str] = Field(min_length=1)
    recommended_mentor_profile: str = Field(default="", max_length=500)

    @field_validator("required_skills", mode="before")
    @classmethod
    def _skills(cls, v: Any) -> Any:
        return _clean_str_list(v)[:10]


class AIAnalysis(BaseModel):
    """The structure Gemini must return. Validated before being trusted."""

    detected_domain: str = Field(min_length=1, max_length=100)
    technologies_identified: list[str] = Field(default_factory=list)
    programming_languages: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    documentation_feedback: list[str] = Field(default_factory=list)
    architecture_suggestions: list[str] = Field(default_factory=list)
    security_concerns: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    additional_features: list[str] = Field(default_factory=list)
    score_breakdown: ScoreBreakdown
    score_explanation: str = Field(min_length=1, max_length=2000)
    mentor_requirements: AIMentorRequirements

    @field_validator(
        "technologies_identified",
        "programming_languages",
        "strengths",
        "weaknesses",
        "improvement_suggestions",
        "documentation_feedback",
        "architecture_suggestions",
        "security_concerns",
        "next_steps",
        "additional_features",
        mode="before",
    )
    @classmethod
    def _lists(cls, v: Any) -> Any:
        return _clean_str_list(v)


# ----------------------------- API response -------------------------------


class Score(BaseModel):
    total: int = Field(ge=0, le=100)
    breakdown: ScoreBreakdown
    explanation: str
    criteria: dict[str, str]
    limitations: str


class MentorRequirements(BaseModel):
    domain: str
    required_skills: list[str]
    recommended_mentor_profile: str


class ProjectAnalysis(BaseModel):
    project_title: str
    detected_domain: str
    technologies_identified: list[str]
    programming_languages: list[str]
    strengths: list[str]
    weaknesses: list[str]
    improvement_suggestions: list[str]
    documentation_feedback: list[str]
    architecture_suggestions: list[str]
    security_concerns: list[str]
    next_steps: list[str]
    additional_features: list[str]
    score: Score
    mentor_requirements: MentorRequirements


class RepositoryInfo(BaseModel):
    full_name: str
    url: str
    default_branch: str
    primary_language: str | None = None
    languages: dict[str, float] = Field(default_factory=dict, description="Language -> percent of code")
    stars: int = 0
    last_pushed_at: str | None = None
    has_readme: bool = False
    has_tests: bool = False
    has_license: bool = False
    total_files: int = 0
    files_analyzed: list[str] = Field(default_factory=list)
    tree_truncated: bool = False


class EvaluationResponse(BaseModel):
    success: bool = True
    project_id: str
    student_id: str
    evaluated_at: datetime
    project_analysis: ProjectAnalysis
    repository: RepositoryInfo
    disclaimer: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict] | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorDetail
