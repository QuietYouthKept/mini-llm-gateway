"""Exact-match prompt cache (in-memory, TTL + LRU eviction).

The cache key is a hash of the canonical request (profile + messages + params),
so identical prompts hit the cache and skip the provider call entirely. This is
the first, deterministic rung of the caching ladder — semantic caching would
come later and brings embedding + threshold + false-hit concerns.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import replace

from app.domain.ports.provider_port import ChatRequest, ChatResponse


class PromptCache:
    def __init__(self, max_entries: int = 256, ttl_ms: int = 300_000) -> None:
        self._max_entries = max(1, max_entries)
        self._ttl_ms = ttl_ms
        self._store: OrderedDict[str, tuple[float, ChatResponse]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(
        request: ChatRequest,
        policy_version: str = "",
        resolved_profile: str | None = None,
    ) -> str:
        payload = {
            "profile": resolved_profile or request.profile,
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "output_policy_version": policy_version,
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return "cache_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

    def get(self, key: str) -> ChatResponse | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            inserted_at, response = entry
            if (time.monotonic() - inserted_at) * 1000 > self._ttl_ms:
                self._store.pop(key, None)
                return None
            # Refresh recency (LRU)
            self._store.move_to_end(key)
            return replace(response, usage=dict(response.usage))

    def put(self, key: str, response: ChatResponse) -> None:
        with self._lock:
            # Store and return defensive copies: callers cannot mutate governance output.
            self._store[key] = (
                time.monotonic(),
                replace(response, usage=dict(response.usage)),
            )
            self._store.move_to_end(key)
            while len(self._store) > self._max_entries:
                self._store.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


# Explicit name for the local backend while retaining the public compatibility alias.
InMemoryPromptCache = PromptCache
