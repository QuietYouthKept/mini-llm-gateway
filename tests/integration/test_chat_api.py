"""End-to-end tests for the gateway data plane."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import auth, chat_payload


def test_chat_success(client: TestClient) -> None:
    resp = client.post("/v1/chat", json=chat_payload("fast-chat"), headers=auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "mock_fast"
    assert body["fallback_used"] is False
    assert body["request_id"]
    assert body["estimated_tokens"] > 0
    assert resp.headers.get("x-request-id") == body["request_id"]


def test_chat_fallback(client: TestClient) -> None:
    resp = client.post("/v1/chat", json=chat_payload("fallback-chat"), headers=auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "mock_fast"
    assert body["fallback_used"] is True
    statuses = [a["status"] for a in body["attempts"]]
    assert "error" in statuses
    assert "success" in statuses


def test_chat_timeout_fallback(client: TestClient) -> None:
    resp = client.post("/v1/chat", json=chat_payload("timeout-chat"), headers=auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "mock_fast"
    assert any(a["status"] == "timeout" for a in body["attempts"])


def test_auth_missing_key(client: TestClient) -> None:
    resp = client.post("/v1/chat", json=chat_payload("fast-chat"))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "auth_failed"


def test_auth_wrong_key(client: TestClient) -> None:
    resp = client.post("/v1/chat", json=chat_payload("fast-chat"), headers=auth("bad"))
    assert resp.status_code == 401


def test_rate_limit(client: TestClient) -> None:
    headers = auth("rl-key")
    payload = chat_payload("fast-chat")
    assert client.post("/v1/chat", json=payload, headers=headers).status_code == 200
    assert client.post("/v1/chat", json=payload, headers=headers).status_code == 200
    resp = client.post("/v1/chat", json=payload, headers=headers)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limit_exceeded"
    assert "Retry-After" in resp.headers


def test_token_budget_exceeded(client: TestClient) -> None:
    payload = chat_payload("fast-chat", content="a" * 400)
    resp = client.post("/v1/chat", json=payload, headers=auth("tiny-key"))
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "token_budget_exceeded"


def test_guardrail_block(client: TestClient) -> None:
    payload = chat_payload("fast-chat", content="please blockme now")
    resp = client.post("/v1/chat", json=payload, headers=auth())
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "guardrail_blocked"


def test_guardrail_max_chars_applies_to_whole_multi_turn_request(client: TestClient) -> None:
    payload = {
        "profile": "fast-chat",
        "messages": [
            {"role": "user", "content": "a" * 2500},
            {"role": "assistant", "content": "b" * 2500},
        ],
    }
    response = client.post("/v1/chat", json=payload, headers=auth())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "guardrail_blocked"


def test_profile_not_found(client: TestClient) -> None:
    resp = client.post("/v1/chat", json=chat_payload("nope"), headers=auth())
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "model_profile_not_found"


def test_streaming_rejected(client: TestClient) -> None:
    payload = chat_payload("fast-chat")
    payload["stream"] = True
    resp = client.post("/v1/chat", json=payload, headers=auth())
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "streaming_not_supported"


def test_audit_lookup(client: TestClient) -> None:
    resp = client.post("/v1/chat", json=chat_payload("fast-chat"), headers=auth())
    request_id = resp.json()["request_id"]
    audit = client.get(f"/v1/requests/{request_id}", headers=auth())
    assert audit.status_code == 200
    body = audit.json()
    assert body["request_id"] == request_id
    assert body["selected_provider"] == "mock_fast"
    assert len(body["attempts"]) >= 1


def test_audit_missing_returns_404(client: TestClient) -> None:
    resp = client.get("/v1/requests/does-not-exist", headers=auth())
    assert resp.status_code == 404


def test_audit_is_scoped_to_authenticated_client(client: TestClient) -> None:
    created = client.post("/v1/chat", json=chat_payload("fast-chat"), headers=auth())
    request_id = created.json()["request_id"]
    response = client.get(f"/v1/requests/{request_id}", headers=auth("tiny-key"))
    assert response.status_code == 404


def test_openai_compatible_endpoint(client: TestClient) -> None:
    payload = {
        "model": "fast-chat",
        "messages": [{"role": "user", "content": "hello"}],
    }
    resp = client.post("/v1/chat/completions", json=payload, headers=auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "fast-chat"
    assert body["choices"][0]["message"]["content"]
    assert body["usage"]["total_tokens"] > 0


def test_metrics_endpoint(client: TestClient) -> None:
    client.post("/v1/chat", json=chat_payload("fast-chat"), headers=auth())
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "llm_gateway_requests_total" in resp.text
    assert "llm_gateway_provider_attempts_total" in resp.text


def test_admin_config_redacts_keys(client: TestClient) -> None:
    resp = client.get("/admin/config", headers={"x-admin-key": "admin-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["admin"]["api_key"] == "***"


def test_admin_requires_key(client: TestClient) -> None:
    resp = client.get("/admin/config")
    assert resp.status_code == 401


def test_admin_reconciles_expired_reservations(client: TestClient) -> None:
    response = client.post(
        "/admin/reconcile-budget-reservations",
        headers={"x-admin-key": "admin-key"},
    )
    assert response.status_code == 200
    assert response.json() == {"reclaimed": 0}
