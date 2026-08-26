"""Tests that unexpected errors do not break the business loop.

Two invariants:
  1. A provider raising a non-domain exception must NOT dead-end the fallback
     chain — it is recorded as a failed attempt and the next provider runs.
  2. An unforeseen failure anywhere in the pipeline must still be written to the
     audit log and surfaced as a structured 500 (InternalError).
"""

from __future__ import annotations

import pytest

from app.application.services.fallback_service import FallbackService
from app.core.request_context import set_request_id
from app.domain.errors import InternalError
from app.domain.models.model_profile import (
    FallbackConfig,
    ModelProfile,
    RoutingCandidate,
    RoutingConfig,
)
from app.domain.ports.provider_port import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ProviderPort,
)
from app.infrastructure.providers.mock_fast import MockFastProvider


class ExplodingProvider(ProviderPort):
    @property
    def provider_id(self) -> str:
        return "exploding"

    @property
    def provider_type(self) -> str:
        return "mock"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        raise RuntimeError("boom")


def make_request() -> ChatRequest:
    return ChatRequest(
        profile="fast-chat",
        messages=[ChatMessage(role="user", content="hi")],
    )


def make_profile(chain: list[str]) -> ModelProfile:
    return ModelProfile(
        profile_id="test",
        routing=RoutingConfig(
            strategy="priority",
            candidates=[
                RoutingCandidate(provider=p, priority=i + 1)
                for i, p in enumerate(chain)
            ],
        ),
        fallback=FallbackConfig(enabled=True, trigger_on=[], chain=chain),
    )


@pytest.mark.asyncio
async def test_fallback_survives_unexpected_provider_error() -> None:
    registry = {"exploding": ExplodingProvider(), "mock_fast": MockFastProvider()}
    service = FallbackService(registry)
    profile = make_profile(["exploding", "mock_fast"])

    response, attempts = await service.execute(
        make_request(), profile, ["exploding", "mock_fast"]
    )

    assert response.provider_id == "mock_fast"
    assert attempts[0].status == "error"
    assert attempts[0].error_code == "provider_failed"
    assert "unexpected error" in attempts[0].error_message
    assert attempts[1].status == "success"


@pytest.mark.asyncio
async def test_unexpected_pipeline_error_is_audited(container, monkeypatch) -> None:
    def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("unexpected boom")

    monkeypatch.setattr(container.chat_service._budget, "reserve", boom)
    set_request_id("rid-unexpected-1")

    request = ChatRequest(
        profile="fast-chat",
        messages=[ChatMessage(role="user", content="hi")],
    )
    client = container.clients_by_id["demo"]

    with pytest.raises(InternalError) as exc:
        await container.chat_service.chat(request, client, endpoint="/v1/chat")

    assert exc.value.error_code == "internal_error"
    audit = container.log_service.get("rid-unexpected-1")
    assert audit is not None
    assert audit["error_code"] == "internal_error"
    assert audit["status_code"] == 500
