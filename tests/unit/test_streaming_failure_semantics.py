"""Contract tests for the streaming failure boundary in ADR-0005."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.application.services.blocking_io import BlockingIOOverloadedError
from app.domain.errors import (
    DatabaseAdmissionOverloadedError,
    InternalError,
    ProviderFailedError,
    ProviderTimeoutError,
)
from app.domain.ports.provider_port import ChatMessage, ChatRequest, ChatResponse, ProviderChunk
from app.infrastructure.persistence.sqlite.connection import get_connection
from app.interfaces.http.routes.chat import _stream_response


def _request(profile: str = "fallback-chat") -> ChatRequest:
    return ChatRequest(
        profile=profile,
        messages=[ChatMessage(role="user", content="stream safely")],
        max_tokens=32,
        stream=True,
    )


def _terminal_state(container, request_id: str) -> dict:
    conn = get_connection(container.db_path)
    try:
        row = conn.execute(
            "SELECT f.operation, f.tokens, f.cost_usd, r.state "
            "FROM stream_finalizations f JOIN token_budget_reservations r "
            "ON r.reservation_id=f.reservation_id WHERE f.request_id=?",
            (request_id,),
        ).fetchone()
        assert row is not None
        result = dict(row)
        result["audit_count"] = conn.execute(
            "SELECT count(*) FROM request_logs WHERE request_id=?", (request_id,)
        ).fetchone()[0]
        result["attempt_count"] = conn.execute(
            "SELECT count(*) FROM provider_attempts WHERE request_id=?", (request_id,)
        ).fetchone()[0]
        return result
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_stream_falls_back_when_first_provider_fails_before_first_token(
    container, monkeypatch
) -> None:
    async def first_provider_fails(_: ChatRequest):
        if False:  # pragma: no cover - keeps this an async generator
            yield ProviderChunk()
        raise ProviderFailedError(provider_id="mock_error", reason="connect failed")

    monkeypatch.setattr(container.providers["mock_error"], "stream_chat", first_provider_fails)
    session = await container.chat_service.start_stream(
        _request(), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]

    messages = [event.data["delta"] for event in events if event.event == "message"]
    assert messages
    assert all("mock_error" not in delta for delta in messages)
    assert events[-1].event == "done"
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "completed"
    assert audit["fallback_used"] == 1
    assert [attempt["provider_id"] for attempt in audit["attempts"]] == [
        "mock_error",
        "mock_fast",
    ]


@pytest.mark.asyncio
async def test_stream_falls_back_on_pre_first_token_timeout(container, monkeypatch) -> None:
    async def first_provider_times_out(_: ChatRequest):
        if False:  # pragma: no cover - keeps this an async generator
            yield ProviderChunk()
        raise ProviderTimeoutError(provider_id="mock_error")

    monkeypatch.setattr(container.providers["mock_error"], "stream_chat", first_provider_times_out)
    session = await container.chat_service.start_stream(
        _request(), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]

    assert any(event.event == "message" for event in events)
    assert not any(event.event == "error" for event in events)
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["attempts"][0]["status"] == "timeout"


@pytest.mark.asyncio
async def test_stream_never_falls_back_after_first_token(container, monkeypatch) -> None:
    async def partial_then_fail(_: ChatRequest):
        yield ProviderChunk(delta="already delivered", index=0)
        raise ProviderFailedError(provider_id="mock_fast", reason="connection reset")

    monkeypatch.setattr(container.providers["mock_fast"], "stream_chat", partial_then_fail)
    session = await container.chat_service.start_stream(
        _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]

    assert [event.event for event in events] == ["message", "error"]
    assert events[-1].data["code"] == "provider_failed"
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "partial_provider_error"
    assert [attempt["provider_id"] for attempt in audit["attempts"]] == ["mock_fast"]


@pytest.mark.asyncio
async def test_metadata_from_failed_provider_is_not_billed_or_copied(
    container, monkeypatch
) -> None:
    async def metadata_then_fail(_: ChatRequest):
        yield ProviderChunk(
            provider_request_id="request-a",
            usage={"prompt_tokens": 90000, "completion_tokens": 90000},
        )
        raise ProviderFailedError(provider_id="mock_error", reason="after metadata")

    async def second_succeeds(_: ChatRequest):
        yield ProviderChunk(delta="from-b", provider_request_id="request-b", index=0)
        yield ProviderChunk(
            finish_reason="stop",
            provider_request_id="request-b",
            usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            index=1,
        )

    monkeypatch.setattr(container.providers["mock_error"], "stream_chat", metadata_then_fail)
    monkeypatch.setattr(container.providers["mock_fast"], "stream_chat", second_succeeds)
    session = await container.chat_service.start_stream(
        _request(), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]

    assert events[-1].event == "done"
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert (audit["actual_input_tokens"], audit["actual_output_tokens"]) == (3, 2)
    assert [attempt["provider_request_id"] for attempt in audit["attempts"]] == [
        "request-a",
        "request-b",
    ]
    assert _terminal_state(container, session.request_id) == {
        "operation": "settle",
        "tokens": 5,
        "cost_usd": 0.0,
        "state": "settled",
        "audit_count": 1,
        "attempt_count": 2,
    }


@pytest.mark.asyncio
async def test_cancel_during_second_provider_records_active_attempt(container, monkeypatch) -> None:
    parked = asyncio.Event()

    async def first_fails(_: ChatRequest):
        yield ProviderChunk(provider_request_id="request-a")
        raise ProviderFailedError(provider_id="mock_error", reason="connect reset")

    async def second_blocks(_: ChatRequest):
        yield ProviderChunk(delta="b-start", provider_request_id="request-b", index=0)
        await parked.wait()
        yield ProviderChunk(delta="unreachable", index=1)

    monkeypatch.setattr(container.providers["mock_error"], "stream_chat", first_fails)
    monkeypatch.setattr(container.providers["mock_fast"], "stream_chat", second_blocks)
    session = await container.chat_service.start_stream(
        _request(), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    assert (await anext(session.events)).data["delta"] == "b-start"
    await session.aclose()

    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "cancelled"
    assert [(a["provider_id"], a["status"]) for a in audit["attempts"]] == [
        ("mock_error", "error"),
        ("mock_fast", "cancelled"),
    ]
    assert [a["provider_request_id"] for a in audit["attempts"]] == [
        "request-a",
        "request-b",
    ]
    state = _terminal_state(container, session.request_id)
    assert state["state"] == "settled"
    assert state["audit_count"] == 1
    assert state["attempt_count"] == 2


@pytest.mark.asyncio
async def test_unstarted_stream_close_releases_and_audits(container) -> None:
    session = await container.chat_service.start_stream(
        _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    await session.aclose()

    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "cancelled"
    assert audit["error_code"] == "client_cancelled"
    state = _terminal_state(container, session.request_id)
    assert state["operation"] == "release"
    assert state["state"] == "released"
    assert state["tokens"] == 0
    assert state["audit_count"] == 1


@pytest.mark.asyncio
async def test_unstarted_asgi_body_close_releases_and_audits(container) -> None:
    session = await container.chat_service.start_stream(
        _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    response = _stream_response(session)
    await response.body_iterator.aclose()

    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "cancelled"
    state = _terminal_state(container, session.request_id)
    assert state["operation"] == "release"
    assert state["state"] == "released"
    assert state["audit_count"] == 1


@pytest.mark.asyncio
async def test_failed_asgi_response_start_releases_unstarted_session(container) -> None:
    session = await container.chat_service.start_stream(
        _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    response = _stream_response(session)

    async def failed_send(_):  # noqa: ANN001, ANN202
        raise RuntimeError("client disconnected before response start")

    with pytest.raises(RuntimeError, match="client disconnected"):
        await response.stream_response(failed_send)

    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "cancelled"
    state = _terminal_state(container, session.request_id)
    assert state["state"] == "released"
    assert state["audit_count"] == 1


@pytest.mark.asyncio
async def test_post_reservation_routing_failure_releases_and_audits(container, monkeypatch) -> None:
    def routing_failure(_):  # noqa: ANN001, ANN202
        raise RuntimeError("routing storage unavailable")

    monkeypatch.setattr(container.routing, "resolve_candidates", routing_failure)
    with pytest.raises(InternalError, match="routing storage unavailable"):
        await container.chat_service.start_stream(
            _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
        )

    conn = get_connection(container.db_path)
    try:
        reservation = conn.execute("SELECT state FROM token_budget_reservations").fetchone()
        audit = conn.execute("SELECT status, error_code FROM request_logs").fetchone()
        finalizations = conn.execute("SELECT count(*) FROM stream_finalizations").fetchone()[0]
    finally:
        conn.close()
    assert reservation["state"] == "released"
    assert dict(audit) == {"status": "admission_failed", "error_code": "internal_error"}
    assert finalizations == 1


@pytest.mark.asyncio
async def test_negative_stream_usage_falls_back_to_nonnegative_estimate(
    container, monkeypatch
) -> None:
    async def negative_usage(_: ChatRequest):
        yield ProviderChunk(delta="safe", index=0)
        yield ProviderChunk(
            finish_reason="stop",
            usage={"prompt_tokens": 3, "completion_tokens": -9},
            index=1,
        )

    monkeypatch.setattr(container.providers["mock_fast"], "stream_chat", negative_usage)
    session = await container.chat_service.start_stream(
        _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]

    assert events[-1].event == "done"
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["usage_source"] == "estimated_invalid_provider_usage"
    assert audit["input_tokens"] >= 0
    assert audit["output_tokens"] >= 0
    assert _terminal_state(container, session.request_id)["tokens"] >= 0


@pytest.mark.asyncio
async def test_negative_buffered_usage_falls_back_to_nonnegative_estimate(
    container, monkeypatch
) -> None:
    async def negative_usage(_: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="safe",
            provider_id="mock_fast",
            usage={"prompt_tokens": 3, "completion_tokens": -9},
        )

    monkeypatch.setattr(container.providers["mock_fast"], "chat", negative_usage)
    outcome = await container.chat_service.chat(
        ChatRequest(
            profile="fast-chat",
            messages=[ChatMessage(role="user", content="safe")],
            max_tokens=32,
        ),
        container.clients_by_id["demo"],
        endpoint="/v1/chat",
    )

    assert outcome.usage_source == "estimated_invalid_provider_usage"
    assert outcome.input_tokens >= 0
    assert outcome.output_tokens >= 0
    assert container.budget_service.snapshot(container.clients_by_id["demo"]).used_tokens >= 0


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
async def test_settlement_rejection_releases_without_false_usage(
    container, monkeypatch, partial: bool
) -> None:
    async def excessive_usage(_: ChatRequest):
        if partial:
            yield ProviderChunk(delta="already sent", index=0)
        yield ProviderChunk(
            finish_reason="stop",
            usage={"prompt_tokens": 500000, "completion_tokens": 500000},
            index=1,
        )

    monkeypatch.setattr(container.providers["mock_fast"], "stream_chat", excessive_usage)
    session = await container.chat_service.start_stream(
        _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]

    assert events[-1].event == "error"
    assert events[-1].data["code"] == "budget_settlement_exceeded"
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "accounting_failed"
    assert audit["error_code"] == "budget_settlement_exceeded"
    assert audit["input_tokens"] == 0
    assert audit["output_tokens"] == 0
    state = _terminal_state(container, session.request_id)
    assert state["operation"] == "release"
    assert state["state"] == "released"
    assert state["tokens"] == 0
    assert state["audit_count"] == 1


@pytest.mark.asyncio
async def test_cancellation_settlement_rejection_is_audited_once(container, monkeypatch) -> None:
    parked = asyncio.Event()

    async def excessive_then_block(_: ChatRequest):
        yield ProviderChunk(
            delta="partial",
            provider_request_id="too-large",
            usage={"prompt_tokens": 500000, "completion_tokens": 500000},
            index=0,
        )
        await parked.wait()

    monkeypatch.setattr(container.providers["mock_fast"], "stream_chat", excessive_then_block)
    session = await container.chat_service.start_stream(
        _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    await anext(session.events)
    await session.aclose()

    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "accounting_failed"
    state = _terminal_state(container, session.request_id)
    assert state["state"] == "released"
    assert state["audit_count"] == 1


@pytest.mark.asyncio
async def test_commit_ack_loss_is_recovered_by_matching_receipt(container, monkeypatch) -> None:
    original = container.stream_finalizer.finalize_stream
    calls = 0

    def commit_then_lose_ack(command):  # noqa: ANN001, ANN202
        nonlocal calls
        calls += 1
        original(command)
        raise OSError("simulated connection loss after commit")

    monkeypatch.setattr(container.stream_finalizer, "finalize_stream", commit_then_lose_ack)
    session = await container.chat_service.start_stream(
        _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]

    assert calls == 1
    assert events[-1].event == "done"
    state = _terminal_state(container, session.request_id)
    assert state["state"] == "settled"
    assert state["audit_count"] == 1


@pytest.mark.asyncio
async def test_unknown_commit_result_is_not_retried_or_assumed_released(
    container, monkeypatch
) -> None:
    calls = 0

    def lose_before_result(command):  # noqa: ANN001, ANN202
        nonlocal calls
        calls += 1
        raise OSError("database result unavailable")

    monkeypatch.setattr(container.stream_finalizer, "finalize_stream", lose_before_result)
    monkeypatch.setattr(container.stream_finalizer, "get_finalization", lambda _: None)
    session = await container.chat_service.start_stream(
        _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]
    await session.aclose()

    assert calls == 1
    assert events[-1].event == "error"
    assert events[-1].data["code"] == "stream_finalization_unknown"
    assert container.log_service.get(session.request_id) is None
    conn = get_connection(container.db_path)
    try:
        state = conn.execute(
            "SELECT state FROM token_budget_reservations WHERE reservation_id LIKE ?",
            (f"{session.request_id}:%",),
        ).fetchone()["state"]
    finally:
        conn.close()
    assert state == "reserved"


@pytest.mark.asyncio
async def test_pre_submission_finalization_overload_does_not_query_commit_receipt(
    container, monkeypatch
) -> None:
    receipt_queries = 0

    async def reject_before_submission(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise BlockingIOOverloadedError("bounded finalization lane is full")

    def get_receipt(_reservation_id: str):
        nonlocal receipt_queries
        receipt_queries += 1
        return None

    monkeypatch.setattr(container.blocking_io, "run", reject_before_submission)
    monkeypatch.setattr(container.stream_finalizer, "get_finalization", get_receipt)
    command = SimpleNamespace(request_id="req-overloaded", reservation_id="req-overloaded:r1")

    with pytest.raises(DatabaseAdmissionOverloadedError):
        await container.chat_service._submit_finalization(command)

    assert receipt_queries == 0


@pytest.mark.asyncio
async def test_disconnect_after_settlement_does_not_refinalize(container, monkeypatch) -> None:
    original = container.stream_finalizer.finalize_stream
    calls = 0

    def counted(command):  # noqa: ANN001, ANN202
        nonlocal calls
        calls += 1
        return original(command)

    monkeypatch.setattr(container.stream_finalizer, "finalize_stream", counted)
    session = await container.chat_service.start_stream(
        _request("fast-chat"), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    async for event in session.events:
        if event.event == "usage":
            break
    await session.aclose()

    assert calls == 1
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert audit["status"] == "completed"
    assert _terminal_state(container, session.request_id)["audit_count"] == 1


@pytest.mark.asyncio
async def test_open_circuit_skips_under_restricted_trigger_policy(container) -> None:
    container.profiles["fallback-chat"].fallback.trigger_on = ["provider_bad_status"]
    breaker = container.circuit_breakers["mock_error"]
    for _ in range(3):
        breaker.record_failure()

    session = await container.chat_service.start_stream(
        _request(), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]

    assert events[-1].event == "done"
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert [(a["provider_id"], a["status"]) for a in audit["attempts"]] == [
        ("mock_error", "circuit_open"),
        ("mock_fast", "success"),
    ]


@pytest.mark.asyncio
async def test_missing_provider_skips_under_restricted_trigger_policy(container) -> None:
    container.profiles["fallback-chat"].fallback.trigger_on = ["provider_bad_status"]
    del container.providers["mock_error"]

    session = await container.chat_service.start_stream(
        _request(), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]

    assert events[-1].event == "done"
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert [(a["provider_id"], a["error_code"]) for a in audit["attempts"]] == [
        ("mock_error", "provider_not_found"),
        ("mock_fast", ""),
    ]


@pytest.mark.asyncio
async def test_open_circuit_does_not_bypass_disabled_fallback(container) -> None:
    container.profiles["fallback-chat"].fallback.enabled = False
    breaker = container.circuit_breakers["mock_error"]
    for _ in range(3):
        breaker.record_failure()

    session = await container.chat_service.start_stream(
        _request(), container.clients_by_id["demo"], endpoint="/v1/chat"
    )
    events = [event async for event in session.events]

    assert [event.event for event in events] == ["error"]
    audit = container.log_service.get(session.request_id)
    assert audit is not None
    assert [(a["provider_id"], a["status"]) for a in audit["attempts"]] == [
        ("mock_error", "circuit_open")
    ]
    assert _terminal_state(container, session.request_id)["state"] == "released"
