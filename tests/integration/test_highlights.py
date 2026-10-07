"""Integration tests for the highlight features: decision trace + cache + replay."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.container import AppContainer
from app.domain.ports.provider_port import ChatMessage, ChatRequest
from tests.conftest import auth, chat_payload


def test_chat_returns_decision_trace(client: TestClient) -> None:
    resp = client.post("/v1/chat", json=chat_payload("fast-chat"), headers=auth())
    assert resp.status_code == 200
    trace = resp.json()["decision_trace"]
    steps = [s["step"] for s in trace]
    assert "profile_resolved" in steps
    assert "provider_selected" in steps
    assert any(s["step"] == "provider_selected" and s["provider"] == "mock_fast" for s in trace)


def test_fallback_decision_trace_explains_skip(client: TestClient) -> None:
    resp = client.post("/v1/chat", json=chat_payload("fallback-chat"), headers=auth())
    assert resp.status_code == 200
    trace = resp.json()["decision_trace"]
    assert any(s["step"] == "provider_failed" and s["provider"] == "mock_error" for s in trace)
    assert any(s["step"] == "provider_selected" and s["provider"] == "mock_fast" for s in trace)


def test_cache_miss_then_hit(client: TestClient) -> None:
    payload = chat_payload("fast-chat", content="unique cache probe 42")
    r1 = client.post("/v1/chat", json=payload, headers=auth())
    r2 = client.post("/v1/chat", json=payload, headers=auth())

    assert r1.json()["cache_hit"] is False
    assert r2.json()["cache_hit"] is True
    assert r2.json()["provider"] == "mock_fast"
    assert r2.json()["cost_saved_usd"] >= 0
    assert r2.json()["attempts"] == []


def test_audit_returns_parsed_decision_trace(client: TestClient) -> None:
    resp = client.post("/v1/chat", json=chat_payload("fast-chat"), headers=auth())
    rid = resp.json()["request_id"]
    audit = client.get(f"/v1/requests/{rid}", headers=auth()).json()
    assert isinstance(audit["decision_trace"], list)
    assert len(audit["decision_trace"]) > 0
    assert isinstance(audit["replay_payload"], dict)


@pytest.mark.asyncio
async def test_replay_reproduces_decision(container: AppContainer) -> None:
    request = ChatRequest(
        profile="fast-chat",
        messages=[ChatMessage(role="user", content="hi")],
    )
    decision = await container.chat_service.replay(
        request,
        "fast-chat",
        recorded_attempts=[{"provider_id": "mock_fast", "status": "success", "retry_index": 0}],
    )
    assert decision["selected_provider"] == "mock_fast"
    assert decision["fallback_used"] is False
    assert decision["attempts"][0]["status"] == "success"
    assert decision["mode"] == "offline"
