"""SQLite persistence for evaluation results (stdlib only)."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path

from app.utils.errors import AppError


class EvaluationStore:
    def __init__(self, database_path: str) -> None:
        self._path = database_path
        self._lock = threading.Lock()
        if database_path != ":memory:":
            Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(database_path, check_same_thread=False)
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS evaluations ("
                "id TEXT PRIMARY KEY, student_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_eval_student ON evaluations(student_id)")
            self._conn.commit()

    def _save(self, project_id: str, student_id: str, created_at: str, payload: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO evaluations (id, student_id, created_at, payload) VALUES (?, ?, ?, ?)",
                (project_id, student_id, created_at, payload),
            )
            self._conn.commit()

    def _get(self, project_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM evaluations WHERE id = ?", (project_id,)).fetchone()
        return row[0] if row else None

    async def save(self, project_id: str, student_id: str, created_at: str, payload: str) -> None:
        try:
            await asyncio.to_thread(self._save, project_id, student_id, created_at, payload)
        except sqlite3.Error as exc:
            raise AppError(500, "STORAGE_ERROR", "The evaluation could not be saved.") from exc

    async def get(self, project_id: str) -> str | None:
        try:
            return await asyncio.to_thread(self._get, project_id)
        except sqlite3.Error as exc:
            raise AppError(500, "STORAGE_ERROR", "The evaluation could not be loaded.") from exc
