"""Simple in-memory sliding-window rate limiter (per client IP)."""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> int:
        """Record a hit. Returns 0 if allowed, otherwise seconds until retry."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window_seconds:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return max(1, int(self.window_seconds - (now - hits[0])) + 1)
            hits.append(now)
            # Opportunistic cleanup so the dict cannot grow without bound.
            if len(self._hits) > 10_000:
                for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window_seconds]:
                    self._hits.pop(k, None)
            return 0
