"""Owner-safe Redis lease used to coalesce cache misses across replicas."""

from __future__ import annotations

import secrets
import threading

_UNLOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisSingleFlight:
    """A short-lived, owner-token-protected distributed singleflight lease.

    Callers must still have a local singleflight: this class only coordinates
    the leader of each process.  A lost Redis connection deliberately returns
    ``None`` so the caller can degrade to local coalescing instead of failing a
    user request.  The token is never used to delete a lease owned by another
    process.
    """

    def __init__(self, url: str, *, ttl_ms: int, prefix: str = "llmgw:sf") -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - environment gate
            raise RuntimeError("Redis backend requires the 'redis' package") from exc
        self._client = redis.Redis.from_url(
            url,
            decode_responses=True,
            protocol=2,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        self._ttl_ms = max(1, ttl_ms)
        self._prefix = prefix
        self._tokens: dict[str, str] = {}
        self._lock = threading.Lock()
        self._unlock = self._client.register_script(_UNLOCK_LUA)

    def try_acquire(self, key: str) -> bool | None:
        """Return owner status, or ``None`` if Redis is unavailable."""
        lock_key = f"{self._prefix}:{key}"
        token = secrets.token_urlsafe(24)
        try:
            acquired = bool(self._client.set(lock_key, token, nx=True, px=self._ttl_ms))
        except Exception:  # Redis is an optional performance dependency.
            return None
        if acquired:
            with self._lock:
                self._tokens[key] = token
        return acquired

    def release(self, key: str) -> bool | None:
        """Release only the lease held by this instance's unique owner token."""
        with self._lock:
            token = self._tokens.pop(key, None)
        if token is None:
            return False
        try:
            return bool(self._unlock(keys=[f"{self._prefix}:{key}"], args=[token]))
        except Exception:  # TTL ensures crash-safe eventual recovery.
            return None

    def close(self) -> None:
        self._client.close()
