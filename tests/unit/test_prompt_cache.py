"""Tests for the exact-match prompt cache."""

from __future__ import annotations

import time

from app.application.services.prompt_cache import PromptCache
from app.domain.ports.provider_port import ChatMessage, ChatRequest, ChatResponse


def make_request(content: str = "hi") -> ChatRequest:
    return ChatRequest(
        profile="fast-chat",
        messages=[ChatMessage(role="user", content=content)],
    )


def make_response() -> ChatResponse:
    return ChatResponse(content="cached", provider_id="mock_fast", model="mock_fast")


def test_key_is_deterministic() -> None:
    assert PromptCache.key(make_request("hi")) == PromptCache.key(make_request("hi"))


def test_key_differs_by_content() -> None:
    assert PromptCache.key(make_request("hi")) != PromptCache.key(make_request("bye"))


def test_key_uses_resolved_default_profile() -> None:
    implicit = make_request("same")
    implicit.profile = ""
    explicit = make_request("same")
    assert PromptCache.key(implicit, resolved_profile="fast-chat") == PromptCache.key(explicit)


def test_get_missing_returns_none() -> None:
    cache = PromptCache()
    assert cache.get("nope") is None


def test_put_get_roundtrip() -> None:
    cache = PromptCache()
    cache.put("k", make_response())
    got = cache.get("k")
    assert got is not None
    assert got.content == "cached"
    assert got.provider_id == "mock_fast"


def test_ttl_expiry() -> None:
    cache = PromptCache(ttl_ms=10)
    cache.put("k", make_response())
    time.sleep(0.03)
    assert cache.get("k") is None


def test_lru_eviction() -> None:
    cache = PromptCache(max_entries=2)
    for i in range(3):
        cache.put(f"k{i}", ChatResponse(content=str(i), provider_id="p"))
    assert cache.get("k0") is None
    assert cache.get("k2") is not None
