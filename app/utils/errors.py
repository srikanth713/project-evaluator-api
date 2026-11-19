"""Application errors that map cleanly to JSON error responses."""

from __future__ import annotations


class AppError(Exception):
    """An expected error with a safe, client-facing message."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def error_body(code: str, message: str, details: list[dict] | None = None) -> dict:
    body: dict = {"success": False, "error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body
