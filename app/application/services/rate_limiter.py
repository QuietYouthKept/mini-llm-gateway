"""In-memory sliding-window rate limiter.

Suitable for a single-process local gateway. A distributed deployment would
swap this for a Redis-based token bucket; the interface stays the same.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_ms: int


class RateLimiter:
    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> RateLimitResult:
        """Return whether a request for 'key' is within the per-window limit."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self._window:
                q.popleft()

            if limit <= 0:
                return RateLimitResult(allowed=False, remaining=0, retry_after_ms=0)

            if len(q) < limit:
                q.append(now)
                return RateLimitResult(
                    allowed=True,
                    remaining=limit - len(q),
                    retry_after_ms=0,
                )

            retry_after_ms = int((self._window - (now - q[0])) * 1000)
            return RateLimitResult(
                allowed=False,
                remaining=0,
                retry_after_ms=max(0, retry_after_ms),
            )


# Explicit local-backend name; RateLimiter remains as a compatibility alias.
InMemoryRateLimiter = RateLimiter
