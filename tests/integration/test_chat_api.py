"""End-to-end tests for the gateway data plane."""

from __future__ import annotations

import sqlite3

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


def test_non_stream_settlement_and_audit_share_finalization_receipt(
    client: TestClient, container
) -> None:
    response = client.post("/v1/chat", json=chat_payload("fast-chat"), headers=auth())
    assert response.status_code == 200
    request_id = response.json()["request_id"]
    with sqlite3.connect(container.db_path) as conn:
        receipt_count = conn.execute(
            "SELECT count(*) FROM stream_finalizations WHERE request_id = ?", (request_id,)
        ).fetchone()[0]
        reservation_states = conn.execute(
            "SELECT r.state FROM token_budget_reservations r "
            "JOIN stream_finalizations f USING (reservation_id) WHERE f.request_id = ?",
            (request_id,),
        ).fetchall()
        request_count = conn.execute(
            "SELECT count(*) FROM request_logs WHERE request_id = ?", (request_id,)
        ).fetchone()[0]
        attempt_count = conn.execute(
            "SELECT count(*) FROM provider_attempts WHERE request_id = ?", (request_id,)
        ).fetchone()[0]
    assert receipt_count == 1
    assert reservation_states == [("settled",)]
    assert request_count == 1
    assert attempt_count == 1


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


def test_database_error_audit_failure_does_not_turn_gateway_error_into_500(
    client: TestClient, container
) -> None:
    headers = auth("rl-key")
    payload = chat_payload("fast-chat")
    assert client.post("/v1/chat", json=payload, headers=headers).status_code == 200
    assert client.post("/v1/chat", json=payload, headers=headers).status_code == 200

    def fail_error_audit(**_kwargs) -> None:  # noqa: ANN003
        raise ConnectionError("simulated PostgreSQL audit outage")

    container.log_service.record_error = fail_error_audit
    response = client.post("/v1/chat", json=payload, headers=headers)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "llm_gateway_audit_failures_total 1" in container.metrics_registry.render()


def test_database_unavailable_releases_local_singleflight(
    client: TestClient, container, monkeypatch
) -> None:
    def fail_snapshot(_client) -> None:  # noqa: ANN001
        raise ConnectionError("simulated PostgreSQL outage")

    monkeypatch.setattr(container.chat_service._budget, "snapshot", fail_snapshot)
    payload = chat_payload("fast-chat", content="same outage request")

    first = client.post("/v1/chat", json=payload, headers=auth())
    second = client.post("/v1/chat", json=payload, headers=auth())

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "database_unavailable"
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "database_unavailable"


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


def test_streaming_returns_sse_and_audits_completion(client: TestClient) -> None:
    payload = chat_payload("fast-chat")
    payload["stream"] = True
    resp = client.post("/v1/chat", json=payload, headers=auth())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "event: message" in resp.text
    assert "event: usage" in resp.text
    assert "event: done" in resp.text
    request_id = resp.headers["x-request-id"]
    audit = client.get(f"/v1/requests/{request_id}", headers=auth()).json()
    assert audit["status"] == "completed"
    assert audit["cache_hit"] == 0


def test_streaming_provider_failure_before_first_token_falls_back(client: TestClient) -> None:
    payload = chat_payload("fallback-chat")
    payload["stream"] = True
    response = client.post("/v1/chat", json=payload, headers=auth())
    assert response.status_code == 200
    assert "event: message" in response.text
    assert "event: done" in response.text
    assert "event: error" not in response.text
    audit = client.get(f"/v1/requests/{response.headers['x-request-id']}", headers=auth()).json()
    assert audit["status"] == "completed"
    assert audit["fallback_used"] == 1
    assert [attempt["provider_id"] for attempt in audit["attempts"]] == [
        "mock_error",
        "mock_fast",
    ]


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
    client.get("/live")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "llm_gateway_requests_total" in resp.text
    assert "llm_gateway_provider_attempts_total" in resp.text
    assert 'llm_gateway_blocking_io_active_workers{lane="database"}' in resp.text
    assert 'llm_gateway_blocking_io_queued_operations{lane="redis"}' in resp.text
    assert 'llm_gateway_http_response_start_seconds_bucket{endpoint="/live"' in resp.text
    assert "llm_gateway_event_loop_lag_seconds" in resp.text
    assert "llm_gateway_event_loop_tasks" in resp.text


def test_lifecycle_phase_metrics_and_traces_are_prompt_free(client: TestClient, container) -> None:
    secret = "do-not-record-this-prompt"
    response = client.post("/v1/chat", json=chat_payload("fast-chat", secret), headers=auth())
    assert response.status_code == 200
    metrics = client.get("/metrics").text
    for phase in (
        "auth.duration",
        "rate_limit.wait",
        "cache.lookup.duration",
        "budget.reserve.duration",
        "routing.duration",
        "provider.duration",
        "audit.persist.duration",
    ):
        assert f'phase="{phase}"' in metrics
    spans = container.tracer.snapshot()
    assert {span.name for span in spans}.issuperset(
        {
            "http.server.request",
            "gateway.request",
            "blocking_io.operation",
            "provider.queue_wait",
            "provider.duration",
        }
    )
    request_span = next(span for span in spans if span.name == "http.server.request")
    assert request_span.attributes["request.id"] == response.json()["request_id"]
    assert request_span.attributes["http.route"] == "/v1/chat"
    assert request_span.attributes["http.response.status_code"] == 200
    assert secret not in str([(span.name, span.attributes) for span in spans])


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
