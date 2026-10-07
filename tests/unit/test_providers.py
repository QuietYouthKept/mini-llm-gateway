"""Tests for mock and fake provider implementations."""

from __future__ import annotations

import pytest

from app.domain.errors import (
    ProviderFailedError,
    ProviderTimeoutError,
)
from app.domain.models.provider import ProviderBehavior
from app.domain.ports.provider_port import ChatMessage, ChatRequest
from app.infrastructure.providers.fake_static import FakeStaticProvider
from app.infrastructure.providers.mock_error import MockErrorProvider
from app.infrastructure.providers.mock_fast import MockFastProvider
from app.infrastructure.providers.mock_slow import MockSlowProvider
from app.infrastructure.providers.mock_stable import MockStableProvider


def make_request(content: str = "hello") -> ChatRequest:
    return ChatRequest(
        profile="fast-chat",
        messages=[ChatMessage(role="user", content=content)],
    )


# ── mock_fast ──


@pytest.mark.asyncio
async def test_mock_fast_returns_response() -> None:
    provider = MockFastProvider()
    response = await provider.chat(make_request("hi"))
    assert response.provider_id == "mock_fast"
    assert "mock_fast" in response.content
    assert "hi" in response.content


@pytest.mark.asyncio
async def test_mock_fast_has_correct_properties() -> None:
    provider = MockFastProvider()
    assert provider.provider_id == "mock_fast"
    assert provider.provider_type == "mock"


@pytest.mark.asyncio
async def test_mock_provider_honors_completion_envelope() -> None:
    provider = MockFastProvider()
    request = make_request("x" * 100)
    request.max_tokens = 3
    response = await provider.chat(request)
    assert len(response.content) <= 12
    assert response.usage["completion_tokens"] <= 3


# ── mock_stable ──


@pytest.mark.asyncio
async def test_mock_stable_returns_response() -> None:
    provider = MockStableProvider()
    response = await provider.chat(make_request("test"))
    assert response.provider_id == "mock_stable"
    assert "mock_stable" in response.content


# ── mock_slow (always timeouts) ──


@pytest.mark.asyncio
async def test_mock_slow_triggers_timeout() -> None:
    provider = MockSlowProvider()
    with pytest.raises(ProviderTimeoutError) as exc:
        await provider.chat(make_request("slow"))
    assert "mock_slow" in str(exc.value)
    assert exc.value.error_code == "provider_timeout"


# ── mock_error (always errors) ──


@pytest.mark.asyncio
async def test_mock_error_triggers_failure() -> None:
    provider = MockErrorProvider()
    with pytest.raises(ProviderFailedError) as exc:
        await provider.chat(make_request("fail"))
    assert "mock_error" in str(exc.value)
    assert exc.value.error_code == "provider_failed"


# ── fake_static (always works) ──


@pytest.mark.asyncio
async def test_fake_static_always_succeeds() -> None:
    provider = FakeStaticProvider()
    response = await provider.chat(make_request("fallback"))
    assert response.provider_id == "fake_static"
    assert "fake_static" in response.content
    assert "fallback" in response.content


@pytest.mark.asyncio
async def test_fake_static_has_correct_type() -> None:
    provider = FakeStaticProvider()
    assert provider.provider_type == "fake_static"


# ── custom behavior ──


@pytest.mark.asyncio
async def test_provider_respects_custom_behavior() -> None:
    behavior = ProviderBehavior(
        latency_ms=1,
        error_rate=0.0,
        timeout_ms=1000,
        default_response="custom response",
    )
    provider = MockFastProvider(behavior=behavior)
    response = await provider.chat(make_request("x"))
    assert "custom response" in response.content
