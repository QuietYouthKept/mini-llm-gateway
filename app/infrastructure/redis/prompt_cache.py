"""Exact governed-response cache shared by Gateway replicas through Redis."""

from __future__ import annotations

import json

from app.domain.ports.provider_port import ChatResponse


class RedisPromptCache:
    def __init__(self, url: str, *, ttl_ms: int, prefix: str = "llmgw:cache") -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - environment gate
            raise RuntimeError("Redis backend requires the 'redis' package") from exc
        self._client = redis.Redis.from_url(url, decode_responses=True, protocol=2)
        self._ttl_ms = max(1, ttl_ms)
        self._prefix = prefix
        self._client.ping()

    def get(self, key: str) -> ChatResponse | None:
        raw = self._client.get(f"{self._prefix}:{key}")
        if raw is None:
            return None
        value = json.loads(raw)
        return ChatResponse(
            content=value["content"],
            provider_id=value["provider_id"],
            model=value.get("model", ""),
            usage=dict(value.get("usage") or {}),
        )

    def put(self, key: str, response: ChatResponse) -> None:
        value = {
            "content": response.content,
            "provider_id": response.provider_id,
            "model": response.model,
            "usage": dict(response.usage),
        }
        self._client.set(
            f"{self._prefix}:{key}",
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            px=self._ttl_ms,
        )

    def healthcheck(self) -> bool:
        return bool(self._client.ping())

    def close(self) -> None:
        self._client.close()
