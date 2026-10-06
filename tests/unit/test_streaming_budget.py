"""Streaming lifecycle tests: partial output must not leak a reservation."""

from __future__ import annotations

import asyncio

import pytest

from app.domain.ports.provider_port import ChatMessage, ChatRequest, ProviderChunk


@pytest.mark.asyncio
async def test_stream_cancellation_settles_observed_output(container, monkeypatch) -> None:
    async def blocking_stream(_: ChatRequest):
        yield ProviderChunk(delta="partial output", index=0)
        await asyncio.Event().wait()

    monkeypatch.setattr(container.providers["mock_fast"], "stream_chat", blocking_stream)
    request = ChatRequest(
        profile="fast-chat",
        messages=[ChatMessage(role="user", content="cancel this stream")],
        max_tokens=32,
        stream=True,
    )
    client = container.clients_by_id["demo"]
    session = await container.chat_service.start_stream(request, client, endpoint="/v1/chat")
    assert (await anext(session.events)).data["delta"] == "partial output"

    next_event = asyncio.create_task(anext(session.events))
    await asyncio.sleep(0)
    next_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await next_event

    snapshot = container.budget_service.snapshot(client)
    assert snapshot.reserved_tokens == 0
    assert snapshot.used_tokens > 0
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "cancelled"


@pytest.mark.asyncio
async def test_stream_timeout_emits_sse_error_and_settles_reservation(
    container, monkeypatch
) -> None:
    async def stalled_stream(_: ChatRequest):
        await asyncio.Event().wait()
        yield ProviderChunk(delta="unreachable")

    container.config.gateway.request_timeout_ms = 10
    monkeypatch.setattr(container.providers["mock_fast"], "stream_chat", stalled_stream)
    client = container.clients_by_id["demo"]
    session = await container.chat_service.start_stream(
        ChatRequest(
            profile="fast-chat",
            messages=[ChatMessage(role="user", content="time out")],
            max_tokens=16,
            stream=True,
        ),
        client,
        endpoint="/v1/chat",
    )
    error = await anext(session.events)
    assert error.event == "error"
    assert error.data["code"] == "request_timeout"
    assert container.budget_service.snapshot(client).reserved_tokens == 0
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "provider_error"
