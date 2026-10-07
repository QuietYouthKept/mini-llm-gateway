"""Tests for FallbackService."""

from __future__ import annotations

import pytest

from app.application.services.fallback_service import FallbackService
from app.application.services.routing_service import RoutingService
from app.domain.errors import FallbackExhaustedError
from app.domain.models.model_profile import (
    FallbackConfig,
    ModelProfile,
    RoutingCandidate,
    RoutingConfig,
)
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


def make_profile(
    profile_id: str = "test",
    fallback_enabled: bool = True,
    fallback_chain: list[str] | None = None,
) -> ModelProfile:
    chain = fallback_chain or ["mock_fast", "mock_stable", "fake_static"]
    return ModelProfile(
        profile_id=profile_id,
        routing=RoutingConfig(
            strategy="priority",
            candidates=[RoutingCandidate(provider=p, priority=i + 1) for i, p in enumerate(chain)],
        ),
        fallback=FallbackConfig(
            enabled=fallback_enabled,
            trigger_on=["provider_error", "timeout", "bad_status"],
            chain=chain,
        ),
    )


# ── success path (happy) ──


@pytest.mark.asyncio
async def test_fallback_first_provider_succeeds() -> None:
    registry = {
        "mock_fast": MockFastProvider(),
    }
    service = FallbackService(registry)
    routing = RoutingService()
    profile = make_profile(fallback_chain=["mock_fast"])
    candidates = routing.resolve_candidates(profile)

    response, attempts = await service.execute(make_request("hi"), profile, candidates)

    assert response.provider_id == "mock_fast"
    assert len(attempts) == 1
    assert attempts[0].status == "success"
    assert attempts[0].provider_id == "mock_fast"


# ── fallback chain: first fails, second succeeds ──


@pytest.mark.asyncio
async def test_fallback_first_error_second_succeeds() -> None:
    registry = {
        "mock_error": MockErrorProvider(),
        "mock_stable": MockStableProvider(),
    }
    service = FallbackService(registry)
    routing = RoutingService()
    profile = make_profile(fallback_chain=["mock_error", "mock_stable"])
    candidates = routing.resolve_candidates(profile)

    response, attempts = await service.execute(make_request("test"), profile, candidates)

    assert response.provider_id == "mock_stable"
    assert len(attempts) == 2
    assert attempts[0].status == "error"
    assert attempts[0].provider_id == "mock_error"
    assert attempts[1].status == "success"
    assert attempts[1].provider_id == "mock_stable"


# ── fallback with timeout ──


@pytest.mark.asyncio
async def test_fallback_timeout_falls_to_next() -> None:
    # mock_slow always timeouts, then mock_fast succeeds
    registry = {
        "mock_slow": MockSlowProvider(),
        "mock_fast": MockFastProvider(),
    }
    service = FallbackService(registry)
    routing = RoutingService()
    profile = make_profile(fallback_chain=["mock_slow", "mock_fast"])
    candidates = routing.resolve_candidates(profile)

    response, attempts = await service.execute(make_request("test"), profile, candidates)

    assert response.provider_id == "mock_fast"
    assert len(attempts) == 2
    assert attempts[0].status == "timeout"
    assert attempts[0].provider_id == "mock_slow"
    assert attempts[1].status == "success"


# ── fake_static as last resort ──


@pytest.mark.asyncio
async def test_fallback_fake_static_last_resort() -> None:
    # All three providers configured; mock_error fails, mock_slow times out, fake_static saves
    registry = {
        "mock_error": MockErrorProvider(),
        "mock_slow": MockSlowProvider(),
        "fake_static": FakeStaticProvider(),
    }
    service = FallbackService(registry)
    routing = RoutingService()
    profile = make_profile(fallback_chain=["mock_error", "mock_slow", "fake_static"])
    candidates = routing.resolve_candidates(profile)

    response, attempts = await service.execute(make_request("last resort"), profile, candidates)

    assert response.provider_id == "fake_static"
    assert len(attempts) == 3
    assert attempts[0].status == "error"
    assert attempts[1].status == "timeout"
    assert attempts[2].status == "success"


# ── fallback exhausted ──


@pytest.mark.asyncio
async def test_fallback_exhausted_raises_error() -> None:
    registry = {
        "mock_error": MockErrorProvider(),
    }
    service = FallbackService(registry)
    routing = RoutingService()
    profile = make_profile(fallback_chain=["mock_error"])
    candidates = routing.resolve_candidates(profile)

    with pytest.raises(FallbackExhaustedError) as exc:
        await service.execute(make_request("doomed"), profile, candidates)

    assert "test" in str(exc.value)
    assert exc.value.error_code == "fallback_exhausted"


# ── fallback disabled: only first candidate tried ──


@pytest.mark.asyncio
async def test_fallback_disabled_stops_after_first() -> None:
    registry = {
        "mock_error": MockErrorProvider(),
        "mock_fast": MockFastProvider(),
    }
    service = FallbackService(registry)
    profile = make_profile(
        fallback_chain=["mock_error", "mock_fast"],
        fallback_enabled=False,
    )

    with pytest.raises(FallbackExhaustedError):
        await service.execute(make_request("nofallback"), profile, ["mock_error", "mock_fast"])


# ── unknown provider in chain ──


@pytest.mark.asyncio
async def test_fallback_unknown_provider_skipped() -> None:
    registry = {
        "mock_fast": MockFastProvider(),
    }
    service = FallbackService(registry)
    routing = RoutingService()
    profile = make_profile(fallback_chain=["ghost", "mock_fast"])
    candidates = routing.resolve_candidates(profile)

    response, attempts = await service.execute(make_request("ghost"), profile, candidates)

    assert response.provider_id == "mock_fast"
    assert len(attempts) == 2
    assert attempts[0].status == "error"
    assert "not found" in attempts[0].error_message
    assert attempts[1].status == "success"


# ── attempt chain contains all metadata ──


@pytest.mark.asyncio
async def test_fallback_attempts_have_correct_order() -> None:
    registry = {
        "mock_error": MockErrorProvider(),
        "mock_fast": MockFastProvider(),
    }
    service = FallbackService(registry)
    routing = RoutingService()
    profile = make_profile(fallback_chain=["mock_error", "mock_fast"])
    candidates = routing.resolve_candidates(profile)

    _, attempts = await service.execute(make_request("order"), profile, candidates)

    assert attempts[0].attempt_order == 0
    assert attempts[1].attempt_order == 1
    assert attempts[0].latency_ms >= 0
    assert attempts[1].latency_ms >= 0
    assert attempts[1].response is not None
    assert "mock_fast" in attempts[1].response["content"]
