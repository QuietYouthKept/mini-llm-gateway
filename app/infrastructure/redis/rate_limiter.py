"""Atomic Redis fixed-window rate limiter for multi-process deployments."""

from __future__ import annotations

from app.application.services.rate_limiter import RateLimitResult
from app.domain.errors import RateLimitBackendUnavailableError

_CHECK_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[2]) end
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then redis.call('PEXPIRE', KEYS[1], ARGV[2]); ttl = tonumber(ARGV[2]) end
local limit = tonumber(ARGV[1])
if count <= limit then return {1, limit - count, 0} end
return {0, 0, ttl}
"""


class RedisRateLimiter:
    def __init__(
        self,
        url: str,
        *,
        window_seconds: float = 60.0,
        prefix: str = "llmgw:rl",
        failure_mode: str = "closed",
    ) -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - environment gate
            raise RuntimeError("Redis backend requires the 'redis' package") from exc
        # RESP2 keeps compatibility with Redis-compatible servers that do not
        # implement redis-py's RESP3 HELLO negotiation.
        self._client = redis.Redis.from_url(
            url,
            decode_responses=True,
            protocol=2,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        self._window_ms = max(1, int(window_seconds * 1000))
        self._prefix = prefix
        self._failure_mode = failure_mode
        self._script = self._client.register_script(_CHECK_LUA)
        self._client.ping()

    def check(self, key: str, limit: int) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(allowed=False, remaining=0, retry_after_ms=0)
        try:
            allowed, remaining, retry_after = self._script(
                keys=[f"{self._prefix}:{key}"], args=[limit, self._window_ms]
            )
        except Exception as exc:
            if self._failure_mode == "open":
                return RateLimitResult(allowed=True, remaining=limit, retry_after_ms=0)
            raise RateLimitBackendUnavailableError() from exc
        return RateLimitResult(bool(allowed), int(remaining), max(0, int(retry_after)))

    def healthcheck(self) -> bool:
        return bool(self._client.ping())

    def close(self) -> None:
        self._client.close()
