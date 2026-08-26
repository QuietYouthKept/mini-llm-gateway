"""Tests for the OpenAI-compatible HTTP provider adapter."""

from __future__ import annotations

import httpx
import pytest

from app.domain.errors import ProviderBadStatusError, ProviderFailedError
from app.domain.ports.provider_port import ChatMessage, ChatRequest
from app.infrastructure.config.config_models import HTTPProviderConfig
from app.infrastructure.providers.openai_compatible import OpenAICompatibleProvider


def make_request() -> ChatRequest:
    return ChatRequest(
        profile="p",
        model="m",
        messages=[ChatMessage(role="user", content="hi")],
    )


def make_provider(handler) -> OpenAICompatibleProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return OpenAICompatibleProvider(
        "openai",
        HTTPProviderConfig(base_url="http://test/v1", api_key="k", model="m"),
        client=client,
    )


@pytest.mark.asyncio
async def test_maps_openai_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hello back"}}],
                "model": "m",
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        )

    provider = make_provider(handler)
    response = await provider.chat(make_request())
    assert response.content == "hello back"
    assert response.usage["total_tokens"] == 7


@pytest.mark.asyncio
async def test_empty_api_key_omits_authorization_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "local"}}],
                "model": "m",
                "usage": {},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        "local",
        HTTPProviderConfig(base_url="http://test/v1", api_key="", model="m"),
        client=client,
    )
    response = await provider.chat(make_request())
    assert response.content == "local"
    await client.aclose()


@pytest.mark.asyncio
async def test_bad_status_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = make_provider(handler)
    with pytest.raises(ProviderBadStatusError):
        await provider.chat(make_request())


@pytest.mark.asyncio
async def test_network_error_raises_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = make_provider(handler)
    with pytest.raises(ProviderFailedError):
        await provider.chat(make_request())
