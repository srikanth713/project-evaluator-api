"""Application configuration, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when the configuration is unsafe or invalid."""


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be an integer.") from exc


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be a number.") from exc


def _get_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """All runtime settings. Secrets are never logged or returned by any endpoint."""

    environment: str = "development"
    app_name: str = "MSGI ONE Project Evaluator API"
    app_version: str = "1.0.0"

    # Credentials (environment variables only)
    gemini_api_key: str = field(default="", repr=False)
    github_token: str = field(default="", repr=False)
    api_access_key: str = field(default="", repr=False)

    # Gemini
    gemini_model: str = "gemini-2.5-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout_seconds: float = 60.0
    gemini_max_output_tokens: int = 8192

    # GitHub
    github_api_url: str = "https://api.github.com"
    github_timeout_seconds: float = 15.0
    allow_private_repos: bool = False

    # Repository content limits
    max_files_to_analyze: int = 10
    max_file_bytes: int = 100_000          # skip files larger than this entirely
    max_chars_per_file: int = 6_000        # truncate each file sent to Gemini
    max_total_chars: int = 40_000          # total repo text sent to Gemini
    max_tree_paths: int = 300              # file paths listed in the prompt

    # API behaviour
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60
    overall_timeout_seconds: float = 120.0
    database_path: str = "data/evaluations.db"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key.strip())

    def validate(self) -> None:
        if "*" in self.cors_origins and self.is_production:
            raise ConfigError(
                "CORS_ORIGINS must list explicit origins in production; '*' is not allowed."
            )

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        settings = cls(
            environment=os.getenv("ENVIRONMENT", "development"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            github_token=os.getenv("GITHUB_TOKEN", "").strip(),
            api_access_key=os.getenv("API_ACCESS_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
            gemini_timeout_seconds=_get_float("GEMINI_TIMEOUT_SECONDS", 60.0),
            github_timeout_seconds=_get_float("GITHUB_TIMEOUT_SECONDS", 15.0),
            allow_private_repos=_get_bool("ALLOW_PRIVATE_REPOS", False),
            max_files_to_analyze=_get_int("MAX_FILES_TO_ANALYZE", 10),
            max_total_chars=_get_int("MAX_TOTAL_CHARS", 40_000),
            cors_origins=_get_list("CORS_ORIGINS", "http://localhost:3000"),
            rate_limit_requests=_get_int("RATE_LIMIT_REQUESTS", 10),
            rate_limit_window_seconds=_get_int("RATE_LIMIT_WINDOW_SECONDS", 60),
            database_path=os.getenv("DATABASE_PATH", "data/evaluations.db"),
        )
        settings.validate()
        return settings
