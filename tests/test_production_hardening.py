"""Evidence-oriented regression, concurrency, and failure-injection tests."""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.application.services.failure_policy import FailurePolicy
from app.application.services.rate_limiter import RateLimiter
from app.application.services.request_log_service import RequestLogService
from app.application.services.token_budget_service import TokenBudgetService
from app.core.container import build_container
from app.core.request_context import set_request_id
from app.domain.errors import (
    RequestDeadlineExceededError,
    TokenBudgetExceededError,
)
from app.domain.models.provider import ProviderAttempt
from app.domain.ports.provider_port import ChatMessage, ChatRequest, ChatResponse, ProviderPort
from app.infrastructure.config.config_models import (
    AppConfig,
    ConfigValidationError,
    LoggingConfig,
)
from app.infrastructure.persistence.sqlite.connection import init_db
from app.infrastructure.persistence.sqlite.repositories import (
    ClientRepository,
    RequestLogRepository,
    TokenBudgetRepository,
)
from app.main import create_app
from tests.conftest import auth, chat_payload, make_test_config


class CountingProvider(ProviderPort):
    def __init__(
        self,
        *,
        content: str = "counted response",
        delay: float = 0.0,
        usage: dict[str, int] | None = None,
    ) -> None:
        self.calls = 0
        self.content = content
        self.delay = delay
        self.usage = usage or {}

    @property
    def provider_id(self) -> str:
        return "mock_fast"

    @property
    def provider_type(self) -> str:
        return "mock"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return ChatResponse(
            content=self.content,
            provider_id=self.provider_id,
            model="test-model",
            usage=self.usage,
        )


def _build_test_container(tmp_path, config: AppConfig | None = None):
    db = str(tmp_path / "hardening.db")
    init_db(db)
    return build_container(config or make_test_config(), db)


def test_cache_stores_governed_output_not_raw_response(tmp_path) -> None:
    config = make_test_config()
    config.guardrails.output_policy.max_chars = 12
    container = _build_test_container(tmp_path, config)
    provider = CountingProvider(content="raw provider response that exceeds policy")
    container.chat_service._fallback._registry["mock_fast"] = provider

    with TestClient(create_app(container)) as client:
        payload = chat_payload("fast-chat", "guarded-cache-regression")
        first = client.post("/v1/chat", json=payload, headers=auth())
        second = client.post("/v1/chat", json=payload, headers=auth())

    assert first.status_code == 200
    assert first.json()["content"] == "raw provider"
    assert second.json()["content"] == first.json()["content"]
    assert second.json()["cache_hit"] is True
    assert second.json()["attempts"] == []
    assert provider.calls == 1


def test_reservation_input_floor_covers_provider_protocol_overhead(tmp_path) -> None:
    config = make_test_config()
    config.token_estimation.reservation_input_floor = 128
    container = _build_test_container(tmp_path, config)
    provider = CountingProvider(usage={"prompt_tokens": 98, "completion_tokens": 16})
    container.chat_service._fallback._registry["mock_fast"] = provider

    with TestClient(create_app(container)) as client:
        response = client.post(
            "/v1/chat",
            json=chat_payload("fast-chat", "short prompt"),
            headers=auth(),
        )

    assert response.status_code == 200
    assert response.json()["actual_input_tokens"] == 98
    assert response.json()["actual_output_tokens"] == 16


def test_replay_and_request_payload_persistence_are_independent_and_safe(tmp_path) -> None:
    config = make_test_config()
    config.logging.persist_request_body = False
    config.logging.persist_replay_payload = False
    container = _build_test_container(tmp_path, config)
    with TestClient(create_app(container)) as client:
        success = client.post(
            "/v1/chat", json=chat_payload("fast-chat", "private message"), headers=auth()
        )
        failure = client.post(
            "/v1/chat", json=chat_payload("fast-chat", "blockme private"), headers=auth()
        )
        success_audit = container.log_service.get(success.json()["request_id"])
        failure_audit = container.log_service.get(failure.json()["error"]["request_id"])

    assert success_audit["request_body"] is None
    assert success_audit["replay_payload"] is None
    assert failure_audit["request_body"] is None
    assert failure_audit["replay_payload"] is None

    enabled = make_test_config()
    enabled.logging.persist_request_body = False
    enabled.logging.persist_replay_payload = True
    second = _build_test_container(tmp_path / "enabled", enabled)
    with TestClient(create_app(second)) as client:
        response = client.post(
            "/v1/chat", json=chat_payload("fast-chat", "replay opt in"), headers=auth()
        )
        audit = second.log_service.get(response.json()["request_id"])
    assert audit["request_body"] is None
    assert audit["replay_payload"]["messages"][0]["content"] == "replay opt in"


def test_budget_reservation_admission_is_atomic_across_connections(tmp_path) -> None:
    config = make_test_config()
    client = config.clients[0]
    client.token_budget.max_tokens = 100
    db = str(tmp_path / "budget-race.db")
    init_db(db)
    ClientRepository(db).sync([client])
    service = TokenBudgetService(TokenBudgetRepository(db))
    service.commit(client, 80, 0.0)
    barrier = threading.Barrier(2)

    def reserve(reservation_id: str) -> str:
        barrier.wait()
        try:
            service.reserve(reservation_id, client, 15)
            return "admitted"
        except TokenBudgetExceededError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ["race-a", "race-b"]))

    assert sorted(results) == ["admitted", "rejected"]
    snapshot = service.snapshot(client)
    assert snapshot.used_tokens + snapshot.reserved_tokens == 95


@pytest.mark.asyncio
async def test_provider_usage_is_used_and_estimator_is_fallback(tmp_path) -> None:
    container = _build_test_container(tmp_path)
    actual = CountingProvider(
        content="provider metered",
        usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    )
    container.chat_service._fallback._registry["mock_fast"] = actual
    set_request_id("usage-provider")
    request = ChatRequest(
        profile="fast-chat",
        messages=[ChatMessage(role="user", content="usage one")],
    )
    outcome = await container.chat_service.chat(
        request, container.clients_by_id["demo"], "/v1/chat"
    )
    assert outcome.usage_source == "provider"
    assert outcome.actual_input_tokens == 7
    assert outcome.actual_output_tokens == 3
    assert outcome.input_tokens + outcome.output_tokens == 10

    estimated = CountingProvider(content="unmetered")
    container.chat_service._fallback._registry["mock_fast"] = estimated
    set_request_id("usage-estimated")
    fallback = await container.chat_service.chat(
        ChatRequest(
            profile="fast-chat",
            messages=[ChatMessage(role="user", content="usage two")],
        ),
        container.clients_by_id["demo"],
        "/v1/chat",
    )
    assert fallback.usage_source == "estimated"
    assert fallback.actual_input_tokens is None
    assert fallback.input_tokens == fallback.estimated_input_tokens


@pytest.mark.asyncio
async def test_offline_replay_never_calls_provider(tmp_path) -> None:
    container = _build_test_container(tmp_path)
    provider = CountingProvider()
    container.chat_service._fallback._registry["mock_fast"] = provider
    decision = await container.chat_service.replay(
        ChatRequest(profile="fast-chat"),
        "fast-chat",
        recorded_attempts=[{"provider_id": "mock_fast", "status": "success"}],
    )
    assert decision["selected_provider"] == "mock_fast"
    assert decision["mode"] == "offline"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_identical_concurrent_misses_are_singleflighted(tmp_path) -> None:
    container = _build_test_container(tmp_path)
    provider = CountingProvider(delay=0.05)
    container.chat_service._fallback._registry["mock_fast"] = provider
    request = ChatRequest(
        profile="fast-chat",
        messages=[ChatMessage(role="user", content="singleflight unique")],
    )

    async def call(request_id: str):
        set_request_id(request_id)
        return await container.chat_service.chat(
            request, container.clients_by_id["demo"], "/v1/chat"
        )

    outcomes = await asyncio.gather(call("singleflight-a"), call("singleflight-b"))
    assert provider.calls == 1
    assert sorted(outcome.cache_hit for outcome in outcomes) == [False, True]


@pytest.mark.asyncio
async def test_overall_deadline_bounds_provider_execution(tmp_path) -> None:
    config = make_test_config()
    config.gateway.request_timeout_ms = 20
    container = _build_test_container(tmp_path, config)
    provider = CountingProvider(delay=0.2)
    container.chat_service._fallback._registry["mock_fast"] = provider
    set_request_id("deadline-test")
    started = time.monotonic()
    with pytest.raises(RequestDeadlineExceededError):
        await container.chat_service.chat(
            ChatRequest(
                profile="fast-chat",
                messages=[ChatMessage(role="user", content="deadline")],
            ),
            container.clients_by_id["demo"],
            "/v1/chat",
        )
    assert time.monotonic() - started < 0.15


def test_audit_request_and_attempts_rollback_together(tmp_path, monkeypatch) -> None:
    db = str(tmp_path / "audit-atomic.db")
    init_db(db)
    repository = RequestLogRepository(db)
    service = RequestLogService(repository, LoggingConfig())
    calls = 0
    original = repository._insert_attempt

    def fail_second(conn, row):  # noqa: ANN001
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected attempt insert failure")
        original(conn, row)

    monkeypatch.setattr(repository, "_insert_attempt", fail_second)
    attempts = [
        ProviderAttempt(provider_id="p1", attempt_order=0, status="error"),
        ProviderAttempt(provider_id="p2", attempt_order=1, status="error"),
    ]
    with pytest.raises(RuntimeError, match="injected"):
        service.record_error(
            request_id="atomic-audit",
            client_id="",
            model_profile="test",
            endpoint="/v1/chat",
            status_code=502,
            error_code="fallback_exhausted",
            error_message="failed",
            duration_ms=1,
            attempts=attempts,
        )
    assert repository.get_request("atomic-audit") is None


def test_http_auth_and_validation_failures_are_correlated_and_audited(
    tmp_path,
) -> None:
    container = _build_test_container(tmp_path)
    with TestClient(create_app(container)) as client:
        unauthorized = client.post("/v1/chat", json=chat_payload("fast-chat"))
        invalid = client.post(
            "/v1/chat",
            json={"profile": "fast-chat", "messages": [{"role": "user"}]},
            headers=auth(),
        )

    for response, code in ((unauthorized, "auth_failed"), (invalid, "validation_error")):
        request_id = response.json()["error"]["request_id"]
        assert response.headers["x-request-id"] == request_id
        audit = container.log_service.get(request_id)
        assert audit["error_code"] == code
        assert audit["status_code"] == response.status_code


def test_hot_reload_build_preserves_long_lived_local_state(tmp_path) -> None:
    config = make_test_config()
    first = _build_test_container(tmp_path, config)
    first.rate_limiter.check("reload-client", 1)
    second = build_container(config, first.db_path, previous=first)
    assert second.rate_limiter is first.rate_limiter
    assert second.prompt_cache is first.prompt_cache
    assert second.metrics_registry is first.metrics_registry
    assert second.singleflight is first.singleflight
    assert second.circuit_breakers["mock_fast"] is first.circuit_breakers["mock_fast"]
    assert second.rate_limiter.check("reload-client", 1).allowed is False


def test_hot_reload_invalidates_cache_when_routing_changes(tmp_path) -> None:
    first_config = make_test_config()
    first = _build_test_container(tmp_path, first_config)
    changed = make_test_config()
    changed.model_profiles["fast-chat"].routing.candidates.reverse()
    second = build_container(changed, first.db_path, previous=first)
    assert second.providers is first.providers
    assert second.prompt_cache is not first.prompt_cache


@pytest.mark.asyncio
async def test_client_cancellation_releases_reservation_and_singleflight(tmp_path) -> None:
    container = _build_test_container(tmp_path)
    provider = CountingProvider(delay=5.0)
    container.chat_service._fallback._registry["mock_fast"] = provider
    set_request_id("rid-cancelled")
    request = ChatRequest(
        profile="fast-chat",
        messages=[ChatMessage(role="user", content="cancel with reservation")],
        max_tokens=64,
    )
    client = container.clients_by_id["demo"]
    task = asyncio.create_task(container.chat_service.chat(request, client, "/v1/chat"))
    while provider.calls == 0:
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    snapshot = container.budget_service.snapshot(client)
    assert snapshot.reserved_tokens == 0
    assert len(container.singleflight._flights) == 0
    audit = container.log_service.get("rid-cancelled")
    assert audit["status_code"] == 499
    assert audit["error_code"] == "client_cancelled"


def test_output_guardrail_error_does_not_duplicate_provider_trace(tmp_path) -> None:
    config = make_test_config()
    config.guardrails.output_policy.blocked_terms = ["forbidden-output"]
    container = _build_test_container(tmp_path, config)
    provider = CountingProvider(content="forbidden-output")
    container.chat_service._fallback._registry["mock_fast"] = provider
    with TestClient(create_app(container)) as client:
        response = client.post(
            "/v1/chat", json=chat_payload("fast-chat", "trace once"), headers=auth()
        )
    assert response.status_code == 400
    audit = container.log_service.get(response.json()["error"]["request_id"])
    provider_steps = [s for s in audit["decision_trace"] if s["step"] == "provider_selected"]
    assert len(provider_steps) == 1


def test_exhausted_fallback_audit_preserves_attempts_and_decision_trace(tmp_path) -> None:
    container = _build_test_container(tmp_path)
    profile = container.profiles["fallback-chat"]
    profile.fallback.chain = ["mock_error"]
    profile.routing.candidates = profile.routing.candidates[:1]
    with TestClient(create_app(container)) as client:
        response = client.post(
            "/v1/chat",
            json=chat_payload("fallback-chat", "exhaust trace"),
            headers=auth(),
        )
    assert response.status_code == 502
    audit = container.log_service.get(response.json()["error"]["request_id"])
    assert len(audit["attempts"]) == 2
    steps = [step["step"] for step in audit["decision_trace"]]
    assert steps.count("provider_failed") == 2
    assert steps[-1] == "error"


def test_failure_policy_is_the_single_classification_oracle() -> None:
    policy = FailurePolicy(["provider_timeout"])
    timeout = policy.decide("provider_timeout", ["timeout"])
    failed = policy.decide("provider_failed", ["timeout"])
    circuit = policy.decide("circuit_open", ["timeout"])
    assert (timeout.retryable, timeout.fallbackable, timeout.affects_circuit) == (
        True,
        True,
        True,
    )
    assert (failed.retryable, failed.fallbackable, failed.affects_circuit) == (
        False,
        False,
        True,
    )
    assert circuit.retryable is False
    assert circuit.fallbackable is True
    assert circuit.affects_circuit is False


def test_rate_limiter_concurrent_requests_do_not_over_admit() -> None:
    limiter = RateLimiter(window_seconds=60)
    barrier = threading.Barrier(32)

    def check(_: int) -> bool:
        barrier.wait()
        return limiter.check("concurrent", 7).allowed

    with ThreadPoolExecutor(max_workers=32) as pool:
        allowed = list(pool.map(check, range(32)))
    assert sum(allowed) == 7


def test_audit_repository_supports_concurrent_writers(tmp_path) -> None:
    db = str(tmp_path / "audit-concurrent.db")
    init_db(db)

    def write(index: int) -> None:
        service = RequestLogService(RequestLogRepository(db), LoggingConfig())
        service.record_error(
            request_id=f"audit-concurrent-{index}",
            client_id="",
            model_profile=None,
            endpoint="/fault",
            status_code=500,
            error_code="injected",
            error_message="fault",
            duration_ms=1,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(24)))
    repository = RequestLogRepository(db)
    assert all(repository.get_request(f"audit-concurrent-{i}") for i in range(24))


def test_metrics_expose_required_low_cardinality_instruments(tmp_path) -> None:
    container = _build_test_container(tmp_path)
    with TestClient(create_app(container)) as client:
        client.post(
            "/v1/chat",
            json=chat_payload("fast-chat", "metrics-hardening"),
            headers=auth(),
        )
        text = client.get("/metrics").text
    required = {
        "llm_gateway_requests_total",
        "llm_gateway_gateway_request_duration_seconds",
        "llm_gateway_provider_attempts_total",
        "llm_gateway_provider_attempt_duration_seconds",
        "llm_gateway_cache_hits_total",
        "llm_gateway_cache_misses_total",
        "llm_gateway_rate_limit_rejections_total",
        "llm_gateway_budget_rejections_total",
        "llm_gateway_circuit_open",
        "llm_gateway_retry_count_total",
        "llm_gateway_fallback_count_total",
        "llm_gateway_audit_failures_total",
    }
    assert required.issubset(text.split())


def test_tracing_records_minimal_spans_without_prompt_or_output(tmp_path) -> None:
    container = _build_test_container(tmp_path)
    secret_text = "never-put-this-in-a-span"
    with TestClient(create_app(container)) as client:
        response = client.post(
            "/v1/chat",
            json=chat_payload("fast-chat", secret_text),
            headers=auth(),
        )
    assert response.status_code == 200
    spans = container.tracer.snapshot()
    assert {span.name for span in spans}.issuperset(
        {"gateway.request", "routing.resolve", "provider.attempt"}
    )
    serialized_attributes = repr([span.attributes for span in spans])
    assert secret_text not in serialized_attributes
    assert response.json()["content"] not in serialized_attributes


def test_unexpected_http_error_is_correlated_and_audited(tmp_path) -> None:
    container = _build_test_container(tmp_path)
    app = create_app(container)

    @app.get("/fault-injection")
    async def fault_injection() -> None:
        raise RuntimeError("injected unexpected HTTP failure")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/fault-injection")
    assert response.status_code == 500
    request_id = response.json()["error"]["request_id"]
    assert response.headers["x-request-id"] == request_id
    audit = container.log_service.get(request_id)
    assert audit["error_code"] == "internal_error"


@pytest.mark.parametrize(
    "raw,match",
    [
        ({"gateway": {"request_timeout_mz": 1}}, "Unknown config field"),
        ({"providers": {"p": {"type": "mystery"}}}, "Unknown provider type"),
        (
            {
                "providers": {"p": {"type": "mock"}},
                "model_profiles": {
                    "m": {
                        "routing": {
                            "strategy": "random-typo",
                            "candidates": [{"provider": "p"}],
                        }
                    }
                },
            },
            "Unknown routing strategy",
        ),
        (
            {
                "providers": {"p": {"type": "mock"}},
                "model_profiles": {
                    "m": {
                        "routing": {"candidates": [{"provider": "missing"}]},
                        "fallback": {"chain": ["missing"]},
                    }
                },
            },
            "unknown/disabled provider",
        ),
    ],
)
def test_config_fails_fast_on_dead_or_unknown_values(raw, match) -> None:  # noqa: ANN001
    with pytest.raises(ConfigValidationError, match=match):
        AppConfig.from_dict(raw)
