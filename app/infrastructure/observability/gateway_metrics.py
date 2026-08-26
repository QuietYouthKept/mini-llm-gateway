"""Concrete metric instruments for the gateway."""

from __future__ import annotations

from app.infrastructure.observability.metrics import MetricsRegistry


class GatewayMetrics:
    def __init__(self, registry: MetricsRegistry) -> None:
        self.requests = registry.counter(
            "requests_total", "Total gateway requests by endpoint and status."
        )
        self.duration = registry.histogram(
            "gateway_request_duration_seconds", "Gateway request latency in seconds."
        )
        self.provider_attempts = registry.counter(
            "provider_attempts_total", "Provider attempts by provider and status."
        )
        self.provider_latency = registry.histogram(
            "provider_attempt_duration_seconds", "Provider attempt latency in seconds."
        )
        self.fallbacks = registry.counter(
            "fallback_count_total", "Requests that used a non-primary provider."
        )
        self.rate_limited = registry.counter(
            "rate_limit_rejections_total", "Requests rejected by rate limiting."
        )
        self.budget_exceeded = registry.counter(
            "budget_rejections_total", "Requests rejected by token/cost budget."
        )
        self.guardrail_blocks = registry.counter(
            "guardrail_blocks_total", "Requests blocked by a guardrail policy."
        )
        self.auth_failed = registry.counter(
            "auth_failed_total", "Requests rejected by authentication."
        )
        self.tokens = registry.counter(
            "tokens_total", "Tokens consumed by client and kind (input/output)."
        )
        self.circuit_state = registry.gauge(
            "circuit_open",
            "Circuit breaker state per provider (0 closed, 1 open, 2 half-open).",
        )
        self.cache_hits = registry.counter(
            "cache_hits_total", "Exact prompt-cache hits."
        )
        self.cache_misses = registry.counter(
            "cache_misses_total", "Exact prompt-cache misses."
        )
        self.cost_saved = registry.counter(
            "estimated_cost_saved_usd_total",
            "Estimated provider cost avoided by cache hits, in USD.",
        )
        self.retries = registry.counter("retry_count_total", "Retried provider attempts.")
        self.audit_failures = registry.counter(
            "audit_failures_total", "Audit writes that failed."
        )
        self.redis_failures = registry.counter(
            "redis_failures_total", "Redis cache, singleflight, or limiter operation failures."
        )
        self.budget_reservation_leaks = registry.counter(
            "budget_reservation_leaks_total",
            "Expired reservations reclaimed by an explicit maintenance run.",
        )

    def record_request(self, endpoint: str, status: str, duration_s: float) -> None:
        self.requests.inc(labels=[("endpoint", endpoint), ("status", status)])
        self.duration.observe(duration_s, labels=[("endpoint", endpoint)])

    def record_attempt(self, provider: str, status: str, latency_ms: int) -> None:
        self.provider_attempts.inc(labels=[("provider", provider), ("status", status)])
        self.provider_latency.observe(latency_ms / 1000.0, labels=[("provider", provider)])

    def record_tokens(self, client: str, kind: str, count: int) -> None:
        if count:
            self.tokens.inc(float(count), labels=[("client", client), ("kind", kind)])

    def record_circuit_state(self, provider: str, state_value: int) -> None:
        self.circuit_state.set(float(state_value), labels=[("provider", provider)])
