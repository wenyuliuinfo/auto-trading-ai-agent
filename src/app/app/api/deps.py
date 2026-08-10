"""Shared API dependencies: run-trigger rate limiting."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import HTTPException, Request

from app.config import get_settings


class RunRateLimiter:
    """In-process sliding-window limiter for run triggers.

    Protects shared free-tier data-vendor quotas from a single user
    firing many concurrent runs (ARCHITECTURE.md §9). In-process is
    sufficient for the current single-process prototype; a Redis-backed
    limiter should replace it if the API is scaled horizontally.
    """

    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> None:
        now = time.monotonic()
        async with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self._window_seconds:
                hits.popleft()
            if len(hits) >= self._limit:
                raise HTTPException(
                    status_code=429,
                    detail="Run trigger rate limit exceeded; try again shortly",
                )
            hits.append(now)


_rate_limiter: RunRateLimiter | None = None


def get_run_rate_limiter() -> RunRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        settings = get_settings()
        _rate_limiter = RunRateLimiter(settings.rate_limit_runs_per_minute)
    return _rate_limiter


async def enforce_run_rate_limit(request: Request) -> None:
    client_ip: Any = request.client.host if request.client else "unknown"
    await get_run_rate_limiter().check(str(client_ip))
