"""Transport contract for the OpenAI-compatible provider adapter."""

from __future__ import annotations

import json

import httpx
import pytest

from app.domain.errors import ProviderBadStatusError
from app.domain.ports.provider_port import ChatMessage, ChatRequest
from app.infrastructure.config.config_models import HTTPProviderConfig
from app.infrastructure.providers.openai_compatible import OpenAICompatibleProvider


def _request() -> ChatRequest:
    return ChatRequest(
        model="contract-model",
        messages=[ChatMessage(role="user", content="contract input")],
        max_tokens=12,
        temperature=0.25,
    )


@pytest.mark.asyncio
async def test_non_streaming_request_and_response_contract() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("authorization")
        observed["tenant"] = request.headers.get("x-tenant")
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"x-request-id": "upstream-request-1"},
            json={
                "id": "body-request-id",
                "model": "provider-model",
                "choices": [{"message": {"content": "contract output"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        "contract-provider",
        HTTPProviderConfig(
            base_url="https://provider.test/v1/",
            api_key="contract-key",
            headers={"X-Tenant": "contract"},
        ),
        client=client,
    )
    try:
        response = await provider.chat(_request())
    finally:
        await client.aclose()

    assert observed == {
        "url": "https://provider.test/v1/chat/completions",
        "authorization": "Bearer contract-key",
        "tenant": "contract",
        "payload": {
            "model": "contract-model",
            "messages": [{"role": "user", "content": "contract input"}],
            "max_tokens": 12,
            "temperature": 0.25,
            "stream": False,
        },
    }
    assert response.content == "contract output"
    assert response.model == "provider-model"
    assert response.usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert response.metadata["provider_request_id"] == "upstream-request-1"


@pytest.mark.asyncio
async def test_streaming_sse_usage_and_done_contract() -> None:
    frames = "\n".join(
        [
            ": keepalive",
            'data: {"id":"chunk-1","choices":[{"delta":{"content":"hello "}}]}',
            (
                'data: {"choices":[{"delta":{"content":"world"},'
                '"finish_reason":"stop"}],"usage":{"prompt_tokens":3,'
                '"completion_tokens":2,"total_tokens":5}}'
            ),
            "data: [DONE]",
            "",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://provider.test/v1/chat/completions"
        assert json.loads(request.content)["stream_options"] == {"include_usage": True}
        return httpx.Response(200, headers={"request-id": "header-id"}, content=frames)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        "contract-provider", HTTPProviderConfig(base_url="https://provider.test/v1"), client=client
    )
    try:
        chunks = [chunk async for chunk in provider.stream_chat(_request())]
    finally:
        await client.aclose()

    assert [(chunk.delta, chunk.finish_reason) for chunk in chunks] == [
        ("hello ", None),
        ("world", "stop"),
    ]
    assert chunks[0].provider_request_id == "chunk-1"
    assert chunks[1].provider_request_id == "header-id"
    assert chunks[1].usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}


@pytest.mark.asyncio
async def test_non_success_status_maps_to_provider_error() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(429, request=request))
    )
    provider = OpenAICompatibleProvider(
        "contract-provider", HTTPProviderConfig(base_url="https://provider.test/v1"), client=client
    )
    try:
        with pytest.raises(ProviderBadStatusError) as raised:
            await provider.chat(_request())
    finally:
        await client.aclose()

    assert raised.value.error_code == "provider_bad_status"
