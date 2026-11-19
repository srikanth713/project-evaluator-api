"""Input validation helpers, including strict GitHub URL parsing (SSRF protection)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_ALLOWED_HOSTS = {"github.com", "www.github.com"}
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


def parse_github_url(url: str) -> tuple[str, str]:
    """Return (owner, repo) for a legitimate https://github.com/<owner>/<repo> URL.

    The server never requests the user-supplied URL. Only the extracted owner/repo
    names are used, and they are sent to the fixed host api.github.com. Anything that
    is not a plain github.com repository URL is rejected.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("GitHub URL is required.")

    candidate = url.strip()
    if len(candidate) > 300:
        raise ValueError("GitHub URL is too long.")

    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError as exc:
        raise ValueError("GitHub URL is malformed.") from exc

    if parts.scheme != "https":
        raise ValueError("GitHub URL must use https://.")
    if parts.username or parts.password or port is not None:
        raise ValueError("GitHub URL must not contain credentials or a port.")
    if (parts.hostname or "").lower() not in _ALLOWED_HOSTS:
        raise ValueError("Only https://github.com repository URLs are accepted.")
    if parts.query or parts.fragment:
        raise ValueError("GitHub URL must not contain a query string or fragment.")

    segments = [s for s in parts.path.split("/") if s]
    if len(segments) != 2:
        raise ValueError("GitHub URL must look like https://github.com/<owner>/<repository>.")

    owner, repo = segments
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _OWNER_RE.match(owner) or "--" in owner:
        raise ValueError("GitHub owner name is invalid.")
    if not _REPO_RE.match(repo) or repo in {".", ".."}:
        raise ValueError("GitHub repository name is invalid.")
    return owner, repo


def normalize_github_url(url: str) -> str:
    owner, repo = parse_github_url(url)
    return f"https://github.com/{owner}/{repo}"


def clean_text(value: str) -> str:
    """Trim and remove control characters (except newlines/tabs)."""
    return "".join(ch for ch in value if ch in "\n\t" or ord(ch) >= 32).strip()
