"""Dependency container — wires config into concrete services.

This is the composition root. Everything the HTTP layer needs hangs off a
single AppContainer instance stored on app.state, which makes hot config
reload a matter of rebuilding the container.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from math import ceil
from typing import Any

from app.application.services.chat_service import ChatService
from app.application.services.circuit_breaker import CircuitBreaker
from app.application.services.fallback_service import FallbackService
from app.application.services.guardrail_service import GuardrailService
from app.application.services.prompt_cache import PromptCache
from app.application.services.rate_limiter import RateLimiter
from app.application.services.request_log_service import RequestLogService
from app.application.services.routing_service import RoutingService
from app.application.services.singleflight import SingleFlight
from app.application.services.token_budget_service import TokenBudgetService
from app.application.services.token_estimator import TokenEstimator
from app.domain.models.model_profile import ModelProfile
from app.domain.ports.provider_port import ProviderPort
from app.domain.ports.repositories import PromptCachePort, RateLimiterPort
from app.infrastructure.config.config_models import AppConfig, ClientConfig
from app.infrastructure.config.mapper import profile_config_to_domain
from app.infrastructure.observability.gateway_metrics import GatewayMetrics
from app.infrastructure.observability.metrics import MetricsRegistry
from app.infrastructure.observability.tracing import OpenTelemetryTraceRecorder, TraceRecorder
from app.infrastructure.persistence.sqlite.repositories import (
    ClientRepository,
    ConfigEventRepository,
    RequestLogRepository,
    TokenBudgetRepository,
)
from app.infrastructure.providers.provider_registry import build_provider_registry


@dataclass
class AppContainer:
    db_path: str
    config: AppConfig
    clients_by_id: dict[str, ClientConfig]
    clients_by_key: dict[str, ClientConfig]
    profiles: dict[str, ModelProfile]
    providers: dict[str, ProviderPort]
    rate_limiter: RateLimiterPort
    budget_service: TokenBudgetService
    estimator: TokenEstimator
    routing: RoutingService
    fallback: FallbackService
    circuit_breakers: dict[str, CircuitBreaker]
    guardrails: GuardrailService
    log_service: RequestLogService
    config_events: Any
    chat_service: ChatService
    metrics_registry: MetricsRegistry
    gateway_metrics: GatewayMetrics
    prompt_cache: PromptCachePort | None
    singleflight: SingleFlight
    distributed_singleflight: Any | None
    tracer: TraceRecorder
    redis_url: str = ""
    cache_backend: str = "local"
    otlp_endpoint: str = ""

    async def close(self, seen: set[int] | None = None) -> None:
        """Close owned provider transports on application shutdown."""
        seen = seen if seen is not None else set()
        for provider in self.providers.values():
            if id(provider) in seen:
                continue
            seen.add(id(provider))
            closer = getattr(provider, "close", None)
            if closer is not None:
                result = closer()
                if hasattr(result, "__await__"):
                    await result
        for resource in (
            self.rate_limiter,
            self.prompt_cache,
            self.distributed_singleflight,
            self.tracer,
        ):
            if resource is None or id(resource) in seen:
                continue
            seen.add(id(resource))
            closer = getattr(resource, "close", None)
            if closer is not None:
                result = closer()
                if hasattr(result, "__await__"):
                    await result


def build_container(
    config: AppConfig,
    db_path: str,
    previous: AppContainer | None = None,
) -> AppContainer:
    is_postgres = db_path.startswith(("postgresql://", "postgres://"))
    if is_postgres:
        from app.infrastructure.persistence.postgresql.repositories import (
            PostgresClientRepository,
            PostgresConfigEventRepository,
            PostgresRequestLogRepository,
            PostgresTokenBudgetRepository,
        )

        client_repository = PostgresClientRepository(db_path)
        budget_repository = PostgresTokenBudgetRepository(db_path)
        request_repository = PostgresRequestLogRepository(db_path)
        config_events = PostgresConfigEventRepository(db_path)
    else:
        client_repository = ClientRepository(db_path)
        budget_repository = TokenBudgetRepository(db_path)
        request_repository = RequestLogRepository(db_path)
        config_events = ConfigEventRepository(db_path)
    client_repository.sync(config.clients)

    clients_by_id = {c.client_id: c for c in config.clients if c.enabled}
    clients_by_key = {c.api_key: c for c in config.clients if c.enabled and c.api_key}

    profiles = {
        pid: profile_config_to_domain(pid, cfg) for pid, cfg in config.model_profiles.items()
    }

    providers = (
        previous.providers
        if previous is not None and previous.config.providers == config.providers
        else build_provider_registry(config.providers)
    )

    redis_url = os.getenv("GW_REDIS_URL", "").strip()
    if previous is not None and redis_url == getattr(previous, "redis_url", ""):
        rate_limiter = previous.rate_limiter
    elif redis_url:
        from app.infrastructure.redis.rate_limiter import RedisRateLimiter

        rate_limiter = RedisRateLimiter(
            redis_url,
            failure_mode=os.getenv("GW_REDIS_RATE_LIMIT_FAILURE_MODE", "closed").lower(),
        )
    else:
        rate_limiter = RateLimiter()
    # The lease must outlive the request deadline. The small wall-clock buffer
    # prevents a maintenance reconciler from reclaiming a still-active request
    # at the boundary between the monotonic request timeout and DB time.
    reservation_lease_seconds = max(
        30,
        ceil(config.gateway.request_timeout_ms / 1000) + 5,
    )
    budget_service = TokenBudgetService(
        budget_repository,
        reservation_lease_seconds=reservation_lease_seconds,
    )
    estimator = TokenEstimator(
        chars_per_token=config.token_estimation.chars_per_token,
        min_tokens=config.token_estimation.min_tokens,
        cost_per_1k_input_usd=config.token_estimation.cost_per_1k_input_tokens_usd,
        cost_per_1k_output_usd=config.token_estimation.cost_per_1k_output_tokens_usd,
    )
    routing = RoutingService()
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    tracer_reusable = (
        previous is not None
        and previous.config.observability == config.observability
        and otlp_endpoint == getattr(previous, "otlp_endpoint", "")
    )
    if tracer_reusable:
        tracer = previous.tracer
    elif config.observability.tracing_enabled and otlp_endpoint:
        tracer = OpenTelemetryTraceRecorder(
            otlp_endpoint,
            max_spans=config.observability.max_spans,
        )
    else:
        tracer = TraceRecorder(
            enabled=config.observability.tracing_enabled,
            max_spans=config.observability.max_spans,
        )

    if previous is not None and previous.config.metrics.prefix == config.metrics.prefix:
        metrics_registry = previous.metrics_registry
        gateway_metrics = previous.gateway_metrics
    else:
        metrics_registry = MetricsRegistry(prefix=config.metrics.prefix)
        gateway_metrics = GatewayMetrics(metrics_registry)

    circuit_breakers: dict[str, CircuitBreaker] = {}
    if config.circuit_breaker.enabled:
        for provider_id in providers:
            old = previous.circuit_breakers.get(provider_id) if previous is not None else None
            if old is not None and previous.config.circuit_breaker == config.circuit_breaker:
                circuit_breakers[provider_id] = old
            else:
                circuit_breakers[provider_id] = CircuitBreaker(
                    provider_id=provider_id,
                    failure_threshold=config.circuit_breaker.failure_threshold,
                    recovery_timeout_ms=config.circuit_breaker.recovery_timeout_ms,
                    half_open_max_calls=config.circuit_breaker.half_open_max_calls,
                )

    fallback = FallbackService(
        providers,
        circuit_breakers=circuit_breakers,
        retry_max=config.retry.max_retries,
        retry_base_delay_ms=config.retry.base_delay_ms,
        retry_max_delay_ms=config.retry.max_delay_ms,
        retry_on=config.retry.retry_on,
        request_timeout_ms=config.gateway.request_timeout_ms,
        tracer=tracer,
        metrics=gateway_metrics,
    )

    guardrails = GuardrailService(config.guardrails)
    cache: PromptCachePort | None = None
    redis_cache = False
    if config.cache.enabled:
        redis_cache = os.getenv("GW_CACHE_BACKEND", "local").lower() == "redis"
        if redis_cache and not redis_url:
            raise RuntimeError("GW_CACHE_BACKEND=redis requires GW_REDIS_URL")
        if redis_cache:
            from app.infrastructure.redis.prompt_cache import RedisPromptCache

            if (
                previous is not None
                and redis_url == getattr(previous, "redis_url", "")
                and previous.cache_backend == "redis"
                and previous.config.cache == config.cache
                and previous.config.providers == config.providers
                and previous.config.model_profiles == config.model_profiles
                and previous.config.guardrails == config.guardrails
            ):
                cache = previous.prompt_cache
            else:
                cache = RedisPromptCache(redis_url, ttl_ms=config.cache.ttl_ms)
        elif (
            previous is not None
            and previous.config.cache == config.cache
            and previous.config.providers == config.providers
            and previous.config.model_profiles == config.model_profiles
            and previous.config.guardrails == config.guardrails
        ):
            cache = previous.prompt_cache
        else:
            cache = PromptCache(max_entries=config.cache.max_entries, ttl_ms=config.cache.ttl_ms)

    log_service = RequestLogService(
        request_repository,
        config.logging,
        tracer=tracer,
        metrics=gateway_metrics,
    )
    singleflight = previous.singleflight if previous is not None else SingleFlight()
    distributed_singleflight = None
    if cache is not None and redis_cache:
        from app.infrastructure.redis.singleflight import RedisSingleFlight

        reuse_distributed = (
            previous is not None
            and redis_url == getattr(previous, "redis_url", "")
            and previous.cache_backend == "redis"
            and previous.config.gateway == config.gateway
            and previous.config.cache == config.cache
        )
        distributed_singleflight = (
            previous.distributed_singleflight
            if reuse_distributed
            else RedisSingleFlight(
                redis_url,
                ttl_ms=max(config.gateway.request_timeout_ms * 2, 5_000),
            )
        )

    chat_service = ChatService(
        config=config,
        profiles=profiles,
        providers=providers,
        clients_by_id=clients_by_id,
        rate_limiter=rate_limiter,
        budget_service=budget_service,
        estimator=estimator,
        routing=routing,
        fallback=fallback,
        circuit_breakers=circuit_breakers,
        guardrails=guardrails,
        log_service=log_service,
        metrics=gateway_metrics,
        cache=cache,
        singleflight=singleflight,
        distributed_singleflight=distributed_singleflight,
        tracer=tracer,
    )

    return AppContainer(
        db_path=db_path,
        config=config,
        clients_by_id=clients_by_id,
        clients_by_key=clients_by_key,
        profiles=profiles,
        providers=providers,
        rate_limiter=rate_limiter,
        budget_service=budget_service,
        estimator=estimator,
        routing=routing,
        fallback=fallback,
        circuit_breakers=circuit_breakers,
        guardrails=guardrails,
        log_service=log_service,
        config_events=config_events,
        chat_service=chat_service,
        metrics_registry=metrics_registry,
        gateway_metrics=gateway_metrics,
        prompt_cache=cache,
        singleflight=singleflight,
        distributed_singleflight=distributed_singleflight,
        tracer=tracer,
        redis_url=redis_url,
        cache_backend=(
            "redis" if os.getenv("GW_CACHE_BACKEND", "local").lower() == "redis" else "local"
        ),
        otlp_endpoint=otlp_endpoint,
    )
