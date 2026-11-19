"""GitHub integration. Read-only, via the GitHub REST API (never clones or executes anything)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from app.config import Settings
from app.utils.errors import AppError

SKIP_DIRS = {
    "node_modules", ".git", "venv", ".venv", "env", "__pycache__", "dist", "build", "vendor",
    "target", ".idea", ".vscode", ".gradle", "pods", ".dart_tool", ".next", "coverage",
    "site-packages", ".pytest_cache", ".mypy_cache", "bin", "obj",
}
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp", ".pdf", ".zip", ".tar",
    ".gz", ".rar", ".7z", ".jar", ".war", ".apk", ".aab", ".exe", ".dll", ".so", ".dylib",
    ".class", ".pyc", ".mp3", ".mp4", ".mov", ".avi", ".wav", ".ttf", ".otf", ".woff",
    ".woff2", ".eot", ".h5", ".hdf5", ".pkl", ".pickle", ".joblib", ".onnx", ".pt", ".pth",
    ".tflite", ".bin", ".db", ".sqlite", ".sqlite3", ".csv", ".tsv", ".parquet", ".xlsx",
    ".xls", ".docx", ".pptx", ".ipynb", ".min.js", ".map", ".lock",
}
LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock",
    "composer.lock", "gemfile.lock", "pubspec.lock", "cargo.lock", "go.sum",
}
MANIFEST_NAMES = {
    "requirements.txt", "pyproject.toml", "setup.py", "pipfile", "package.json", "pubspec.yaml",
    "build.gradle", "build.gradle.kts", "settings.gradle", "pom.xml", "cargo.toml", "go.mod",
    "composer.json", "gemfile", "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "platformio.ini", "androidmanifest.xml", "environment.yml", "makefile",
}
ENTRYPOINT_NAMES = {
    "main.py", "app.py", "manage.py", "run.py", "server.py", "index.js", "server.js", "app.js",
    "main.js", "index.ts", "main.ts", "app.ts", "main.dart", "main.go", "main.rs", "main.cpp",
    "main.c", "main.java", "mainactivity.java", "mainactivity.kt", "main.ino", "index.html",
    "app.jsx", "app.tsx", "index.php",
}
CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".dart", ".go", ".rs", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".php", ".rb", ".swift", ".ino", ".sol", ".sql", ".sh", ".html",
    ".css", ".vue", ".yml", ".yaml", ".toml", ".md",
}
SENSITIVE_RE = re.compile(
    r"(^|/)(\.env(\..*)?|.*\.pem|.*\.key|.*\.p12|.*\.pfx|id_rsa|id_ed25519|secrets?\.(json|ya?ml)|"
    r"credentials(\.json)?|google-services\.json|serviceaccount.*\.json)$",
    re.IGNORECASE,
)
README_RE = re.compile(r"^readme(\.[a-z]+)?$", re.IGNORECASE)


@dataclass
class RepositorySnapshot:
    full_name: str
    html_url: str
    description: str | None
    default_branch: str
    primary_language: str | None
    languages: dict[str, float]
    stars: int
    last_pushed_at: str | None
    topics: list[str]
    private: bool
    archived: bool
    tree_paths: list[str]
    total_files: int
    tree_truncated: bool
    has_readme: bool
    has_tests: bool
    has_license: bool
    sensitive_files: list[str]
    files: dict[str, str] = field(default_factory=dict)  # path -> (truncated) text content


class GitHubService:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    # ------------------------------------------------------------------ HTTP

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "msgi-one-project-evaluator",
        }
        if self._settings.github_token:
            headers["Authorization"] = f"Bearer {self._settings.github_token}"
        return headers

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict | None = None,
        accept: str = "application/vnd.github+json",
    ) -> httpx.Response:
        # Only the fixed GitHub API host is ever contacted.
        try:
            resp = await client.get(path, params=params, headers=self._headers(accept))
        except httpx.TimeoutException as exc:
            raise AppError(504, "GITHUB_TIMEOUT", "GitHub did not respond in time. Please try again.") from exc
        except httpx.RequestError as exc:
            raise AppError(502, "GITHUB_UNREACHABLE", "Could not reach GitHub. Please try again later.") from exc

        if resp.status_code == 401:
            raise AppError(502, "GITHUB_AUTH_FAILED", "The server's GitHub credentials are invalid.")
        if resp.status_code in (403, 429):
            remaining = resp.headers.get("x-ratelimit-remaining")
            body = resp.text.lower() if resp.content else ""
            if resp.status_code == 429 or remaining == "0" or "rate limit" in body:
                raise AppError(
                    429,
                    "GITHUB_RATE_LIMITED",
                    "GitHub API rate limit reached. Please try again later.",
                )
        if resp.status_code >= 500:
            raise AppError(502, "GITHUB_ERROR", "GitHub returned an error. Please try again later.")
        return resp

    # ------------------------------------------------------------ public API

    async def fetch_repository(self, owner: str, repo: str, private_consent: bool = False) -> RepositorySnapshot:
        s = self._settings
        async with httpx.AsyncClient(
            base_url=s.github_api_url,
            timeout=s.github_timeout_seconds,
            transport=self._transport,
            follow_redirects=False,
        ) as client:
            owner_q, repo_q = quote(owner, safe=""), quote(repo, safe="")
            meta_resp = await self._get(client, f"/repos/{owner_q}/{repo_q}")
            if meta_resp.status_code == 404:
                raise AppError(
                    404,
                    "REPO_NOT_FOUND",
                    "Repository not found. It may not exist or it may be private.",
                )
            if meta_resp.status_code in (403, 451):
                raise AppError(403, "REPO_INACCESSIBLE", "This repository is not accessible to the evaluator.")
            if meta_resp.status_code in (301, 302, 307, 308):
                raise AppError(404, "REPO_NOT_FOUND", "Repository has moved; submit its current GitHub URL.")
            if meta_resp.status_code != 200:
                raise AppError(502, "GITHUB_ERROR", "Unexpected response from GitHub.")
            meta = meta_resp.json()

            if meta.get("private") and not (s.allow_private_repos and private_consent):
                raise AppError(
                    403,
                    "REPO_PRIVATE",
                    "This repository is private. Private repositories are only analysed with the "
                    "student's explicit consent and when the server administrator has enabled it.",
                )

            default_branch = meta.get("default_branch") or "main"
            languages = await self._fetch_languages(client, owner_q, repo_q)
            tree_paths, sizes, truncated = await self._fetch_tree(client, owner_q, repo_q, default_branch)
            if not tree_paths:
                raise AppError(422, "EMPTY_REPOSITORY", "The repository is empty, so there is nothing to evaluate.")

            selected, sensitive = self._select_files(tree_paths, sizes)
            files = await self._fetch_files(client, owner_q, repo_q, default_branch, selected)

        names_lower = [p.lower() for p in tree_paths]
        return RepositorySnapshot(
            full_name=meta.get("full_name") or f"{owner}/{repo}",
            html_url=meta.get("html_url") or f"https://github.com/{owner}/{repo}",
            description=meta.get("description"),
            default_branch=default_branch,
            primary_language=meta.get("language"),
            languages=languages,
            stars=int(meta.get("stargazers_count") or 0),
            last_pushed_at=meta.get("pushed_at"),
            topics=[str(t) for t in (meta.get("topics") or [])][:15],
            private=bool(meta.get("private")),
            archived=bool(meta.get("archived")),
            tree_paths=[p for p in tree_paths if not self._in_skipped_dir(p)][: s.max_tree_paths],
            total_files=len(tree_paths),
            tree_truncated=truncated,
            has_readme=any(README_RE.match(p) for p in tree_paths),
            has_tests=any(
                re.search(r"(^|/)(tests?|__tests__|spec)(/|$)|(^|/)test_[^/]+|[^/]+_test\.|\.(test|spec)\.", p)
                for p in names_lower
            ),
            has_license=any(re.match(r"^(license|licence|copying)(\.[a-z]+)?$", p) for p in names_lower),
            sensitive_files=sensitive[:10],
            files=files,
        )

    # ------------------------------------------------------------- internals

    async def _fetch_languages(self, client: httpx.AsyncClient, owner: str, repo: str) -> dict[str, float]:
        resp = await self._get(client, f"/repos/{owner}/{repo}/languages")
        if resp.status_code != 200:
            return {}
        raw = resp.json()
        total = sum(v for v in raw.values() if isinstance(v, (int, float))) or 0
        if not total:
            return {}
        return {k: round(v * 100 / total, 1) for k, v in raw.items() if isinstance(v, (int, float))}

    async def _fetch_tree(
        self, client: httpx.AsyncClient, owner: str, repo: str, branch: str
    ) -> tuple[list[str], dict[str, int], bool]:
        resp = await self._get(
            client,
            f"/repos/{owner}/{repo}/git/trees/{quote(branch, safe='')}",
            params={"recursive": "1"},
        )
        if resp.status_code in (404, 409):  # 409 = "Git Repository is empty."
            return [], {}, False
        if resp.status_code != 200:
            raise AppError(502, "GITHUB_ERROR", "Could not read the repository file list.")
        data = resp.json()
        paths: list[str] = []
        sizes: dict[str, int] = {}
        for entry in data.get("tree", []):
            if entry.get("type") == "blob" and isinstance(entry.get("path"), str):
                paths.append(entry["path"])
                sizes[entry["path"]] = int(entry.get("size") or 0)
        return paths, sizes, bool(data.get("truncated"))

    @staticmethod
    def _in_skipped_dir(path: str) -> bool:
        return any(part.lower() in SKIP_DIRS for part in path.split("/")[:-1])

    def _select_files(self, paths: list[str], sizes: dict[str, int]) -> tuple[list[str], list[str]]:
        """Choose the most informative text files. Returns (selected, sensitive_files_found)."""
        sensitive: list[str] = []
        scored: list[tuple[tuple[int, int, int, str], str]] = []
        for path in paths:
            if self._in_skipped_dir(path):
                continue
            if SENSITIVE_RE.search(path):
                sensitive.append(path)  # reported by name only; content is never fetched
                continue
            name = path.rsplit("/", 1)[-1]
            lower = name.lower()
            ext = "." + lower.rsplit(".", 1)[-1] if "." in lower else ""
            if lower in LOCKFILES or ext in BINARY_EXTENSIONS or lower.endswith(".min.js"):
                continue
            size = sizes.get(path, 0)
            if size == 0 or size > self._settings.max_file_bytes:
                continue
            depth = path.count("/")
            if depth == 0 and README_RE.match(name):
                rank = 0
            elif lower in MANIFEST_NAMES and depth <= 2:
                rank = 1
            elif lower in ENTRYPOINT_NAMES:
                rank = 2
            elif ext in CODE_EXTENSIONS and ext != ".md":
                is_test = bool(re.search(r"test|spec", path.lower()))
                rank = 4 if is_test else 3
            elif ext == ".md" and path.lower().startswith("docs/"):
                rank = 5
            else:
                continue
            scored.append(((rank, depth, -size, path), path))
        scored.sort(key=lambda item: item[0])
        return [p for _, p in scored[: self._settings.max_files_to_analyze]], sensitive

    async def _fetch_files(
        self, client: httpx.AsyncClient, owner: str, repo: str, branch: str, selected: list[str]
    ) -> dict[str, str]:
        sem = asyncio.Semaphore(4)
        budget = self._settings.max_total_chars
        per_file = self._settings.max_chars_per_file

        async def fetch(path: str) -> tuple[str, str | None]:
            async with sem:
                encoded = "/".join(quote(seg, safe="") for seg in path.split("/"))
                resp = await self._get(
                    client,
                    f"/repos/{owner}/{repo}/contents/{encoded}",
                    params={"ref": branch},
                    accept="application/vnd.github.raw+json",
                )
            if resp.status_code != 200:
                return path, None
            raw = resp.content[: self._settings.max_file_bytes]
            if b"\x00" in raw:  # binary content
                return path, None
            return path, raw.decode("utf-8", errors="replace")[:per_file]

        results = await asyncio.gather(*(fetch(p) for p in selected))
        files: dict[str, str] = {}
        used = 0
        for path, text in results:  # preserves priority order
            if not text or not text.strip():
                continue
            remaining = budget - used
            if remaining <= 0:
                break
            text = text[:remaining]
            files[path] = text
            used += len(text)
        return files
