"""Correctness-first orchestration for the gateway data plane."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Literal

from app.application.dto.chat_dto import AttemptDetail, ChatOutcome
from app.application.services.blocking_io import (
    BlockingIOOverloadedError,
    BoundedBlockingIO,
)
from app.application.services.circuit_breaker import CircuitBreaker, CircuitState
from app.application.services.fallback_service import FallbackService
from app.application.services.guardrail_service import GuardrailService
from app.application.services.prompt_cache import PromptCache
from app.application.services.request_log_service import RequestLogService
from app.application.services.routing_service import RoutingService
from app.application.services.singleflight import SingleFlight
from app.application.services.token_budget_service import TokenBudgetService
from app.application.services.token_estimator import TokenEstimator
from app.core.request_context import get_request_id
from app.domain.errors import (
    BudgetSettlementExceededError,
    DatabaseUnavailableError,
    FallbackExhaustedError,
    GatewayError,
    GuardrailBlockedError,
    InternalError,
    ModelProfileNotFoundError,
    ProviderTimeoutError,
    RateLimitExceededError,
    ReplayUnavailableError,
    RequestDeadlineExceededError,
    StreamFinalizationUnknownError,
    StreamingNotSupportedError,
    http_status_for,
)
from app.domain.models.decision_trace import DecisionStep
from app.domain.models.model_profile import ModelProfile
from app.domain.models.provider import ProviderAttempt
from app.domain.ports.provider_port import (
    ChatRequest,
    ChatResponse,
    ProviderPort,
)
from app.domain.ports.repositories import (
    FinalizationConflictError,
    FinalizationReceipt,
    FinalizationRejectedError,
    FinalizeStreamCommand,
    PromptCachePort,
    RateLimiterPort,
    StreamingFinalizationRepositoryPort,
)
from app.infrastructure.config.config_models import AppConfig, ClientConfig
from app.infrastructure.observability.gateway_metrics import GatewayMetrics
from app.infrastructure.observability.tracing import TraceRecorder

logger = logging.getLogger(__name__)

_CIRCUIT_STATE_VALUE = {
    CircuitState.CLOSED: 0,
    CircuitState.OPEN: 1,
    CircuitState.HALF_OPEN: 2,
}
_MAX_PROVIDER_USAGE_TOKENS = 2_147_483_647


@dataclass
class StreamEvent:
    event: str
    data: dict[str, Any]


@dataclass
class StreamingSession:
    """A prepared stream; admission completes before HTTP headers are sent."""

    request_id: str
    events: AsyncIterator[StreamEvent]
    close_unstarted: Callable[[], Awaitable[None]]

    async def aclose(self) -> None:
        closer = getattr(self.events, "aclose", None)
        if closer is not None:
            await closer()
        await self.close_unstarted()


@dataclass(frozen=True)
class _StreamFinalization:
    receipt: FinalizationReceipt
    usage: dict[str, Any]
    accounting_error: GatewayError | None = None


@dataclass
class _StreamLifecycle:
    started: bool = False


class ChatService:
    def __init__(
        self,
        config: AppConfig,
        profiles: dict[str, ModelProfile],
        providers: dict[str, ProviderPort],
        clients_by_id: dict[str, ClientConfig],
        rate_limiter: RateLimiterPort,
        budget_service: TokenBudgetService,
        estimator: TokenEstimator,
        routing: RoutingService,
        fallback: FallbackService,
        circuit_breakers: dict[str, CircuitBreaker],
        guardrails: GuardrailService,
        log_service: RequestLogService,
        stream_finalizer: StreamingFinalizationRepositoryPort,
        metrics: GatewayMetrics,
        cache: PromptCachePort | None = None,
        singleflight: SingleFlight | None = None,
        distributed_singleflight: Any | None = None,
        tracer: TraceRecorder | None = None,
        blocking_io: BoundedBlockingIO | None = None,
    ) -> None:
        self._config = config
        self._profiles = profiles
        self._providers = providers
        self._clients = clients_by_id
        self._rate_limiter = rate_limiter
        self._budget = budget_service
        self._estimator = estimator
        self._routing = routing
        self._fallback = fallback
        self._circuit_breakers = circuit_breakers
        self._guardrails = guardrails
        self._log_service = log_service
        self._stream_finalizer = stream_finalizer
        self._metrics = metrics
        self._cache = cache
        self._cache_enabled = config.cache.enabled and cache is not None
        self._singleflight = singleflight or SingleFlight()
        self._distributed_singleflight = distributed_singleflight
        self._tracer = tracer or TraceRecorder(enabled=False)
        self._blocking_io = blocking_io or BoundedBlockingIO()

    async def chat(
        self,
        request: ChatRequest,
        client: ClientConfig,
        endpoint: str,
    ) -> ChatOutcome:
        with self._tracer.span("gateway.request", {"endpoint": endpoint}) as span:
            try:
                outcome = await self._chat(request, client, endpoint)
                span.attributes.update(
                    {
                        "status": "success",
                        "provider": outcome.provider_id,
                        "model": outcome.model,
                        "cache_hit": outcome.cache_hit,
                        "fallback_used": outcome.fallback_used,
                    }
                )
                return outcome
            except GatewayError as exc:
                span.attributes["status"] = exc.error_code
                raise

    async def _chat(
        self,
        request: ChatRequest,
        client: ClientConfig,
        endpoint: str,
    ) -> ChatOutcome:
        request_id = get_request_id()
        start = time.monotonic()
        deadline_at = start + self._config.gateway.request_timeout_ms / 1000.0
        attempts: list[ProviderAttempt] = []
        trace: list[DecisionStep] = []
        model_profile: str | None = None
        replay_payload = self._request_body_snapshot(request)
        reservation_id: str | None = None
        flight: tuple[str, asyncio.Event] | None = None
        distributed_flight_key: str | None = None
        provider_trace_recorded = False
        durable_finalized = False

        try:
            self._enforce_streaming(request, request_id)
            trace.append(DecisionStep(step="streaming_checked", meta={"allowed": True}))

            with self._phase("rate_limit.wait"):
                await self._blocking_io.run(self._enforce_rate_limit, client, request_id)
            trace.append(
                DecisionStep(
                    step="rate_limit_checked",
                    meta={
                        "allowed": True,
                        "limit_per_minute": client.rate_limit.requests_per_minute,
                    },
                )
            )

            profile, profile_id = self._resolve_profile(request, request_id)
            model_profile = profile_id
            trace.append(
                DecisionStep(
                    step="profile_resolved",
                    meta={"profile": profile_id, "intent": profile.intent or ""},
                )
            )

            self._enforce_guardrails_input(request, request_id)
            trace.append(DecisionStep(step="guardrail_input_checked", meta={"allowed": True}))

            estimated_input = self._estimator.estimate_messages(request.messages)
            cache_key = PromptCache.key(
                request,
                self._guardrails.policy_version,
                resolved_profile=profile_id,
            )

            cached = await self._cache_get(cache_key, trace) if self._cache_enabled else None
            if cached is not None:
                return await self._serve_cache_hit(
                    cached,
                    request_id,
                    client,
                    profile_id,
                    endpoint,
                    estimated_input,
                    cache_key,
                    start,
                    trace,
                    replay_payload,
                )

            if self._cache_enabled:
                self._metrics.cache_misses.inc()
                while True:
                    owner, event = self._singleflight.acquire(cache_key)
                    if owner:
                        flight = (cache_key, event)
                        break
                    trace.append(
                        DecisionStep(
                            step="cache_coalesced",
                            reason="waiting for identical in-flight request",
                            meta={"key": cache_key},
                        )
                    )
                    remaining = deadline_at - time.monotonic()
                    if remaining <= 0:
                        raise RequestDeadlineExceededError(request_id=request_id)
                    try:
                        with self._phase("singleflight.wait"):
                            await asyncio.wait_for(event.wait(), timeout=remaining)
                    except TimeoutError as exc:
                        raise RequestDeadlineExceededError(request_id=request_id) from exc
                    cached = await self._cache_get(cache_key, trace)
                    if cached is not None:
                        return await self._serve_cache_hit(
                            cached,
                            request_id,
                            client,
                            profile_id,
                            endpoint,
                            estimated_input,
                            cache_key,
                            start,
                            trace,
                            replay_payload,
                        )

                distributed_flight_key = await self._acquire_distributed_flight(
                    cache_key, deadline_at, trace
                )
                cached = await self._cache_get(cache_key, trace)
                if cached is not None:
                    await self._release_distributed_flight(distributed_flight_key)
                    distributed_flight_key = None
                    self._release_flight(flight)
                    flight = None
                    return await self._serve_cache_hit(
                        cached,
                        request_id,
                        client,
                        profile_id,
                        endpoint,
                        estimated_input,
                        cache_key,
                        start,
                        trace,
                        replay_payload,
                    )

            trace.append(
                DecisionStep(step="cache_miss", reason="no exact match", meta={"key": cache_key})
            )

            budget_before = await self._blocking_io.run(
                self._budget.snapshot, client, dependency="database"
            )
            reserved_input = max(
                estimated_input,
                self._config.token_estimation.reservation_input_floor,
            )
            reserved_tokens = reserved_input + max(0, request.max_tokens)
            reserved_cost = self._estimator.cost_usd(reserved_input, max(0, request.max_tokens))
            reservation_id = f"{request_id}:{uuid.uuid4().hex}"
            with self._phase("budget.reserve.duration"):
                reserved = await self._blocking_io.run(
                    self._budget.reserve,
                    reservation_id,
                    client,
                    reserved_tokens,
                    reserved_cost,
                    dependency="database",
                )
            trace.append(
                DecisionStep(
                    step="budget_reserved",
                    meta={
                        "tokens": reserved_tokens,
                        "input_floor_applied": reserved_input != estimated_input,
                        "remaining_after_reservation": reserved.remaining_tokens,
                    },
                )
            )

            with self._phase("routing.duration", {"profile": profile.profile_id}) as routing_span:
                # Keep the original semantic span for existing trace queries while
                # exposing the plan's duration-oriented phase name.
                with self._tracer.span(
                    "routing.resolve", {"profile": profile.profile_id}
                ) as resolve_span:
                    candidates = self._routing.resolve_candidates(profile)
                    resolve_span.attributes["candidate_count"] = len(candidates)
                routing_span.attributes["candidate_count"] = len(candidates)
            response, attempts = await self._fallback.execute(
                request,
                profile,
                candidates,
                deadline_at=deadline_at,
            )
            trace.extend(self._build_provider_trace(candidates, attempts))
            provider_trace_recorded = True

            content = self._enforce_guardrails_output(response, request_id)
            trace.append(DecisionStep(step="guardrail_output_checked", meta={"allowed": True}))

            governed_response = replace(response, content=content, usage=dict(response.usage))
            estimated_output = self._estimator.estimate_text(content)
            usage = self._resolve_usage(response, estimated_input, estimated_output)
            billed_input = usage["billed_input"]
            billed_output = usage["billed_output"]
            cost_usd = self._estimator.cost_usd(billed_input, billed_output)
            trace.append(
                DecisionStep(
                    step="budget_finalization_requested",
                    meta={"usage_source": usage["source"]},
                )
            )
            selected_provider = self._providers.get(response.provider_id)
            if selected_provider is None:
                raise InternalError("Selected provider is not available", request_id=request_id)
            with self._phase("budget.settle.duration"):
                terminal = await self._finalize_stream(
                    request_id=request_id,
                    reservation_id=reservation_id,
                    operation="settle",
                    client=client,
                    endpoint=endpoint,
                    profile_id=profile_id,
                    provider=selected_provider,
                    provider_usage=response.usage,
                    estimated_input=estimated_input,
                    content=content,
                    budget_before=budget_before.remaining_tokens,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    attempts=attempts,
                    trace=trace,
                    replay_payload=replay_payload,
                    status="success",
                    status_code=200,
                )
            durable_finalized = True
            reservation_id = None
            if terminal.accounting_error is not None:
                raise terminal.accounting_error
            budget_after = terminal.receipt.budget_after
            trace.append(
                DecisionStep(
                    step="budget_settled",
                    meta={
                        "remaining_after": budget_after,
                        "usage_source": usage["source"],
                    },
                )
            )

            if self._cache_enabled:
                await self._cache_put(cache_key, governed_response, trace)
            await self._release_distributed_flight(distributed_flight_key)
            distributed_flight_key = None
            self._release_flight(flight)
            flight = None

            fallback_used = any(a.status != "success" for a in attempts)
            duration_ms = int((time.monotonic() - start) * 1000)
            estimated_total = estimated_input + estimated_output

            self._record_success_metrics(
                endpoint,
                client,
                billed_input,
                billed_output,
                attempts,
                fallback_used,
                duration_ms,
            )
            self.sync_circuit_metrics()

            return ChatOutcome(
                request_id=request_id,
                content=content,
                provider_id=response.provider_id,
                model=response.model or response.provider_id,
                attempts=[AttemptDetail.from_attempt(a) for a in attempts],
                decision_trace=[s.to_dict() for s in trace],
                input_tokens=billed_input,
                output_tokens=billed_output,
                estimated_tokens=estimated_total,
                estimated_input_tokens=estimated_input,
                estimated_output_tokens=estimated_output,
                actual_input_tokens=usage["actual_input"],
                actual_output_tokens=usage["actual_output"],
                usage_source=usage["source"],
                estimated_cost_usd=cost_usd,
                budget_before=budget_before.remaining_tokens,
                budget_after=budget_after,
                fallback_used=fallback_used,
                cache_hit=False,
                cache_key=cache_key,
                duration_ms=duration_ms,
            )

        except GatewayError as exc:
            if durable_finalized or isinstance(
                exc, (DatabaseUnavailableError, StreamFinalizationUnknownError)
            ):
                self._record_error_metrics(exc, endpoint, int((time.monotonic() - start) * 1000))
                raise
            logger.warning(
                "Request gateway error before durable error audit code=%s request_id=%s",
                exc.error_code,
                request_id,
            )
            if reservation_id is not None:
                try:
                    await self._blocking_io.run(
                        self._budget.release, reservation_id, dependency="database"
                    )
                except Exception as release_exc:
                    if self._is_database_unavailable(release_exc):
                        self._metrics.budget_reservation_leaks.inc()
                        self._metrics.audit_failures.inc()
                        raise DatabaseUnavailableError(request_id=request_id) from release_exc
                    raise
            await self._release_distributed_flight(distributed_flight_key)
            self._release_flight(flight)
            attempts = self._attempts_from_error(exc, attempts)
            if attempts and not provider_trace_recorded:
                trace.extend(self._build_provider_trace([], attempts))
            duration_ms = int((time.monotonic() - start) * 1000)
            trace.append(
                DecisionStep(step="error", reason=exc.error_code, meta={"message": str(exc)})
            )
            try:
                await self._blocking_io.run(
                    self._log_service.record_error,
                    request_id=request_id,
                    client_id=client.client_id,
                    model_profile=model_profile,
                    endpoint=endpoint,
                    status_code=http_status_for(exc.error_code),
                    error_code=exc.error_code,
                    error_message=str(exc),
                    duration_ms=duration_ms,
                    attempts=attempts,
                    request_body=replay_payload,
                    decision_trace=[s.to_dict() for s in trace],
                    replay_payload=replay_payload,
                    dependency="database",
                )
            except Exception as audit_exc:
                self._metrics.audit_failures.inc()
                if self._is_database_unavailable(audit_exc):
                    raise DatabaseUnavailableError(request_id=request_id) from audit_exc
                # An audit defect must never replace the actual request error.
            self._record_error_metrics(exc, endpoint, duration_ms)
            self.sync_circuit_metrics()
            raise

        except asyncio.CancelledError:
            if reservation_id is not None:
                try:
                    receipt = await self._blocking_io.run(
                        self._stream_finalizer.get_finalization,
                        reservation_id,
                        dependency="database",
                        recovery_probe=True,
                    )
                    durable_finalized = receipt is not None and receipt.request_id == request_id
                except Exception:
                    # Never release on an unqueryable commit outcome.  The
                    # lease and reconciler remain the durable recovery path.
                    durable_finalized = True
                    self._metrics.audit_failures.inc()
                if durable_finalized:
                    reservation_id = None
                else:
                    await self._blocking_io.run(
                        self._budget.release, reservation_id, dependency="database"
                    )
            await self._release_distributed_flight(distributed_flight_key)
            self._release_flight(flight)
            if attempts and not provider_trace_recorded:
                trace.extend(self._build_provider_trace([], attempts))
            duration_ms = int((time.monotonic() - start) * 1000)
            trace.append(DecisionStep(step="error", reason="client_cancelled"))
            if not durable_finalized:
                await self._blocking_io.run(
                    self._log_service.record_error,
                    request_id=request_id,
                    client_id=client.client_id,
                    model_profile=model_profile,
                    endpoint=endpoint,
                    status_code=499,
                    error_code="client_cancelled",
                    error_message="Client cancelled request",
                    duration_ms=duration_ms,
                    attempts=attempts,
                    request_body=replay_payload,
                    decision_trace=[s.to_dict() for s in trace],
                    replay_payload=replay_payload,
                    dependency="database",
                )
                self._metrics.record_request(endpoint, "client_cancelled", duration_ms / 1000.0)
            self.sync_circuit_metrics()
            raise

        except Exception as exc:
            if durable_finalized:
                self._metrics.audit_failures.inc()
                raise
            if self._is_database_unavailable(exc):
                if reservation_id is not None:
                    self._metrics.budget_reservation_leaks.inc()
                self._metrics.audit_failures.inc()
                error = DatabaseUnavailableError(request_id=request_id)
                self._record_error_metrics(
                    error, endpoint, int((time.monotonic() - start) * 1000)
                )
                raise error from exc
            if reservation_id is not None:
                await self._blocking_io.run(
                    self._budget.release, reservation_id, dependency="database"
                )
            await self._release_distributed_flight(distributed_flight_key)
            self._release_flight(flight)
            duration_ms = int((time.monotonic() - start) * 1000)
            trace.append(
                DecisionStep(step="error", reason="internal_error", meta={"message": str(exc)})
            )
            await self._blocking_io.run(self._log_service.record_error,
                request_id=request_id,
                client_id=client.client_id,
                model_profile=model_profile,
                endpoint=endpoint,
                status_code=500,
                error_code="internal_error",
                error_message=str(exc),
                duration_ms=duration_ms,
                attempts=attempts,
                request_body=replay_payload,
                decision_trace=[s.to_dict() for s in trace],
                replay_payload=replay_payload,
                dependency="database",
            )
            self._metrics.record_request(endpoint, "internal_error", duration_ms / 1000.0)
            self.sync_circuit_metrics()
            raise InternalError(message=str(exc), request_id=request_id) from exc

    async def start_stream(
        self, request: ChatRequest, client: ClientConfig, endpoint: str
    ) -> StreamingSession:
        """Run stream admission before HTTP starts and never cache partial output."""
        request_id = get_request_id()
        start = time.monotonic()
        trace: list[DecisionStep] = []
        replay_payload = self._request_body_snapshot(request)
        self._enforce_streaming(request, request_id)
        with self._phase("rate_limit.wait"):
            await self._blocking_io.run(self._enforce_rate_limit, client, request_id)
        trace.append(DecisionStep(step="rate_limit_checked", meta={"allowed": True}))
        profile, profile_id = self._resolve_profile(request, request_id)
        trace.append(DecisionStep(step="profile_resolved", meta={"profile": profile_id}))
        self._enforce_guardrails_input(request, request_id)
        trace.append(DecisionStep(step="guardrail_input_checked", meta={"allowed": True}))
        # A stream may be cancelled or fail after bytes have been sent, so it
        # is intentionally neither read from nor written to the exact cache.
        trace.append(
            DecisionStep(step="cache_skipped", reason="streaming responses are not cached")
        )

        estimated_input = self._estimator.estimate_messages(request.messages)
        reserved_input = max(estimated_input, self._config.token_estimation.reservation_input_floor)
        reservation_id = f"{request_id}:{uuid.uuid4().hex}"
        reserve_submitted = False
        try:
            budget_before = await self._blocking_io.run(
                self._budget.snapshot, client, dependency="database"
            )
            with self._phase("budget.reserve.duration"):
                reserve_submitted = True
                await self._blocking_io.run(
                    self._budget.reserve,
                    reservation_id,
                    client,
                    reserved_input + max(0, request.max_tokens),
                    self._estimator.cost_usd(reserved_input, max(0, request.max_tokens)),
                    dependency="database",
                )
        except Exception as exc:
            if not self._is_database_unavailable(exc):
                raise
            if reserve_submitted and not isinstance(exc, BlockingIOOverloadedError):
                self._metrics.budget_reservation_leaks.inc()
            self._metrics.audit_failures.inc()
            error = DatabaseUnavailableError(request_id=request_id)
            self._record_error_metrics(error, endpoint, int((time.monotonic() - start) * 1000))
            raise error from exc
        trace.append(DecisionStep(step="budget_reserved"))
        try:
            candidates = self._routing.resolve_candidates(profile)
            if not candidates:
                raise InternalError("No streaming provider is available", request_id=request_id)
            if not profile.fallback.enabled:
                candidates = candidates[:1]
            lifecycle = _StreamLifecycle()
            return StreamingSession(
                request_id=request_id,
                events=self._stream_events(
                    request_id=request_id,
                    request=request,
                    client=client,
                    endpoint=endpoint,
                    profile_id=profile_id,
                    candidates=candidates,
                    reservation_id=reservation_id,
                    estimated_input=estimated_input,
                    budget_before=budget_before.remaining_tokens,
                    trace=trace,
                    replay_payload=replay_payload,
                    start=start,
                    lifecycle=lifecycle,
                ),
                close_unstarted=lambda: self._finalize_unstarted_stream(
                    request_id=request_id,
                    reservation_id=reservation_id,
                    client=client,
                    endpoint=endpoint,
                    profile_id=profile_id,
                    estimated_input=estimated_input,
                    budget_before=budget_before.remaining_tokens,
                    trace=trace,
                    replay_payload=replay_payload,
                    start=start,
                    lifecycle=lifecycle,
                ),
            )
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, GatewayError)
                else InternalError(message=str(exc), request_id=request_id)
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            failure_trace = [
                *trace,
                DecisionStep(step="error", reason=error.error_code, meta={"phase": "admission"}),
            ]
            await self._finalize_stream(
                request_id=request_id,
                reservation_id=reservation_id,
                operation="release",
                client=client,
                endpoint=endpoint,
                profile_id=profile_id,
                provider=None,
                provider_usage=None,
                estimated_input=estimated_input,
                content="",
                budget_before=budget_before.remaining_tokens,
                duration_ms=duration_ms,
                attempts=[],
                trace=failure_trace,
                replay_payload=replay_payload,
                status="admission_failed",
                status_code=http_status_for(error.error_code),
                error_code=error.error_code,
                error_message=str(error),
            )
            self._record_error_metrics(error, endpoint, duration_ms)
            raise error from exc

    async def _stream_events(
        self,
        *,
        request_id: str,
        request: ChatRequest,
        client: ClientConfig,
        endpoint: str,
        profile_id: str,
        candidates: list[str],
        reservation_id: str,
        estimated_input: int,
        budget_before: int,
        trace: list[DecisionStep],
        replay_payload: dict[str, Any],
        start: float,
        lifecycle: _StreamLifecycle,
    ) -> AsyncIterator[StreamEvent]:
        """Stream provider output and persist one atomic terminal decision."""
        lifecycle.started = True
        content = ""
        provider_usage: dict[str, int] | None = None
        finish_reason = "stop"
        attempts: list[ProviderAttempt] = []
        provider: ProviderPort | None = None
        active_attempt: ProviderAttempt | None = None
        first_token_sent = False
        provider_invoked = False
        finalized = False
        deadline_at = start + self._config.gateway.request_timeout_ms / 1000.0

        try:
            for order, provider_id in enumerate(candidates):
                if deadline_at <= time.monotonic():
                    raise RequestDeadlineExceededError(request_id=request_id)
                candidate = self._providers.get(provider_id)
                if candidate is None:
                    attempts.append(
                        ProviderAttempt(
                            provider_id=provider_id,
                            attempt_order=order,
                            status="error",
                            error_code="provider_not_found",
                            error_message="Provider is not available in the registry",
                        )
                    )
                    continue
                circuit = self._circuit_breakers.get(provider_id)
                if circuit is not None and not circuit.allow_request():
                    attempts.append(
                        ProviderAttempt(
                            provider_id=provider_id,
                            attempt_order=order,
                            status="circuit_open",
                            error_code="circuit_open",
                            error_message="circuit breaker is open",
                        )
                    )
                    continue

                provider = candidate
                provider_usage = None
                provider_invoked = True
                attempt_started = time.monotonic()
                attempt = ProviderAttempt(
                    provider_id=provider_id,
                    attempt_order=order,
                    status="success",
                )
                active_attempt = attempt
                attempt_finish_reason = "stop"
                try:
                    async with asyncio.timeout(deadline_at - time.monotonic()):
                        async for chunk in candidate.stream_chat(request):
                            if chunk.provider_request_id:
                                attempt.provider_request_id = chunk.provider_request_id
                            if chunk.usage:
                                provider_usage = chunk.usage
                            attempt_finish_reason = chunk.finish_reason or attempt_finish_reason
                            if not chunk.delta:
                                continue
                            candidate_content = content + chunk.delta
                            decision = self._guardrails.check_output(candidate_content)
                            if not decision.allowed:
                                raise GuardrailBlockedError(
                                    message=f"Streaming output blocked ({decision.reason})",
                                    request_id=request_id,
                                )
                            content = (
                                decision.content
                                if decision.content is not None
                                else candidate_content
                            )
                            first_token_sent = True
                            yield StreamEvent(
                                event="message",
                                data={
                                    "delta": chunk.delta,
                                    "request_id": request_id,
                                    "index": chunk.index,
                                },
                            )
                except TimeoutError:
                    exc = ProviderTimeoutError(provider_id=provider_id, request_id=request_id)
                    self._handle_stream_candidate_failure(
                        exc,
                        attempt,
                        attempt_started,
                        circuit,
                        attempts,
                        trace,
                        first_token_sent,
                    )
                    active_attempt = None
                    if not first_token_sent and self._stream_can_fallback(exc, profile_id):
                        provider = None
                        provider_invoked = False
                        continue
                    raise exc from None
                except Exception as exc:
                    self._handle_stream_candidate_failure(
                        exc,
                        attempt,
                        attempt_started,
                        circuit,
                        attempts,
                        trace,
                        first_token_sent,
                    )
                    active_attempt = None
                    if not first_token_sent and self._stream_can_fallback(exc, profile_id):
                        provider = None
                        provider_invoked = False
                        continue
                    raise

                attempt.latency_ms = int((time.monotonic() - attempt_started) * 1000)
                attempts.append(attempt)
                active_attempt = None
                finish_reason = attempt_finish_reason
                if circuit is not None:
                    circuit.record_success()
                break
            else:
                error = FallbackExhaustedError(profile_id=profile_id, request_id=request_id)
                error.attempts = attempts  # type: ignore[attr-defined]
                raise error

            if provider is None:
                raise FallbackExhaustedError(profile_id=profile_id, request_id=request_id)
            trace.extend(self._build_provider_trace(candidates, attempts))
            trace.append(
                DecisionStep(
                    step="budget_finalization_requested",
                    meta={
                        "observed_chars": len(content),
                        "observed_output_tokens": self._estimator.estimate_text(content),
                    },
                )
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            terminal = await self._finalize_stream(
                request_id=request_id,
                reservation_id=reservation_id,
                operation="settle",
                client=client,
                endpoint=endpoint,
                profile_id=profile_id,
                provider=provider,
                provider_usage=provider_usage,
                estimated_input=estimated_input,
                content=content,
                budget_before=budget_before,
                duration_ms=duration_ms,
                attempts=attempts,
                trace=trace,
                replay_payload=replay_payload,
                status="completed",
                status_code=200,
            )
            finalized = True
            if terminal.accounting_error is not None:
                self._record_error_metrics(terminal.accounting_error, endpoint, duration_ms)
                yield self._stream_error_event(terminal.accounting_error, request_id)
                return
            usage = terminal.usage
            self._record_success_metrics(
                endpoint,
                client,
                usage["billed_input"],
                usage["billed_output"],
                attempts,
                len(attempts) > 1,
                duration_ms,
            )
            yield StreamEvent(
                event="usage",
                data={
                    "input_tokens": usage["billed_input"],
                    "output_tokens": usage["billed_output"],
                    "usage_source": usage["source"],
                },
            )
            yield StreamEvent("done", {"finish_reason": finish_reason, "request_id": request_id})
        except (asyncio.CancelledError, GeneratorExit):
            if finalized:
                raise
            if active_attempt is not None and active_attempt not in attempts:
                active_attempt.status = "cancelled"
                active_attempt.latency_ms = int((time.monotonic() - start) * 1000)
                attempts.append(active_attempt)
            duration_ms = int((time.monotonic() - start) * 1000)
            cancel_trace = [
                *trace,
                *self._build_provider_trace(candidates, attempts),
                DecisionStep(
                    step="cancelled",
                    meta={
                        "observed_chars": len(content),
                        "observed_output_tokens": self._estimator.estimate_text(content),
                    },
                ),
            ]
            try:
                terminal = await self._finalize_stream(
                    request_id=request_id,
                    reservation_id=reservation_id,
                    operation=(
                        "settle" if provider is not None and provider_invoked else "release"
                    ),
                    client=client,
                    endpoint=endpoint,
                    profile_id=profile_id,
                    provider=provider,
                    provider_usage=provider_usage,
                    estimated_input=estimated_input,
                    content=content,
                    budget_before=budget_before,
                    duration_ms=duration_ms,
                    attempts=attempts,
                    trace=cancel_trace,
                    replay_payload=replay_payload,
                    status="cancelled",
                    status_code=499,
                    error_code="client_cancelled",
                    error_message="Client cancelled request",
                )
                finalized = True
                if terminal.accounting_error is not None:
                    self._record_error_metrics(terminal.accounting_error, endpoint, duration_ms)
            except StreamFinalizationUnknownError as exc:
                self._record_error_metrics(exc, endpoint, duration_ms)
            raise
        except StreamFinalizationUnknownError as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            self._record_error_metrics(exc, endpoint, duration_ms)
            yield self._stream_error_event(exc, request_id)
        except Exception as exc:
            if finalized:
                raise
            error_code = getattr(exc, "error_code", "provider_failed")
            duration_ms = int((time.monotonic() - start) * 1000)
            error_trace = [
                *trace,
                *self._build_provider_trace(candidates, attempts),
                DecisionStep(
                    step="error",
                    reason=error_code,
                    meta={
                        "observed_chars": len(content),
                        "observed_output_tokens": self._estimator.estimate_text(content),
                    },
                ),
            ]
            status = "guardrail_blocked" if error_code == "guardrail_blocked" else "provider_error"
            if content:
                status = f"partial_{status}"
            try:
                terminal = await self._finalize_stream(
                    request_id=request_id,
                    reservation_id=reservation_id,
                    operation=(
                        "settle" if provider is not None and provider_invoked else "release"
                    ),
                    client=client,
                    endpoint=endpoint,
                    profile_id=profile_id,
                    provider=provider,
                    provider_usage=provider_usage,
                    estimated_input=estimated_input,
                    content=content,
                    budget_before=budget_before,
                    duration_ms=duration_ms,
                    attempts=attempts,
                    trace=error_trace,
                    replay_payload=replay_payload,
                    status=status,
                    status_code=http_status_for(error_code),
                    error_code=error_code,
                    error_message=str(exc),
                )
                finalized = True
                outbound_error: BaseException = terminal.accounting_error or exc
            except StreamFinalizationUnknownError as finalization_error:
                outbound_error = finalization_error
            metric_error = (
                outbound_error
                if isinstance(outbound_error, GatewayError)
                else InternalError(request_id=request_id)
            )
            self._record_error_metrics(metric_error, endpoint, duration_ms)
            yield self._stream_error_event(outbound_error, request_id)

    async def _finalize_unstarted_stream(
        self,
        *,
        request_id: str,
        reservation_id: str,
        client: ClientConfig,
        endpoint: str,
        profile_id: str,
        estimated_input: int,
        budget_before: int,
        trace: list[DecisionStep],
        replay_payload: dict[str, Any],
        start: float,
        lifecycle: _StreamLifecycle,
    ) -> None:
        if lifecycle.started:
            return
        try:
            if await self._blocking_io.run(
                self._stream_finalizer.get_finalization,
                reservation_id,
                dependency="database",
                recovery_probe=True,
            ) is not None:
                return
        except Exception as exc:
            raise StreamFinalizationUnknownError(request_id=request_id) from exc
        await self._finalize_stream(
            request_id=request_id,
            reservation_id=reservation_id,
            operation="release",
            client=client,
            endpoint=endpoint,
            profile_id=profile_id,
            provider=None,
            provider_usage=None,
            estimated_input=estimated_input,
            content="",
            budget_before=budget_before,
            duration_ms=int((time.monotonic() - start) * 1000),
            attempts=[],
            trace=[*trace, DecisionStep(step="cancelled", reason="stream_not_consumed")],
            replay_payload=replay_payload,
            status="cancelled",
            status_code=499,
            error_code="client_cancelled",
            error_message="Stream was closed before consumption started",
        )

    async def _finalize_stream(
        self,
        *,
        request_id: str,
        reservation_id: str,
        operation: Literal["settle", "release"],
        client: ClientConfig,
        endpoint: str,
        profile_id: str,
        provider: ProviderPort | None,
        provider_usage: dict[str, int] | None,
        estimated_input: int,
        content: str,
        budget_before: int,
        duration_ms: int,
        attempts: list[ProviderAttempt],
        trace: list[DecisionStep],
        replay_payload: dict[str, Any],
        status: str,
        status_code: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> _StreamFinalization:
        estimated_output = self._estimator.estimate_text(content)
        if operation == "settle":
            if provider is None:
                raise ValueError("settlement requires an invoked provider")
            usage = self._resolve_usage(
                ChatResponse(
                    content=content,
                    provider_id=provider.provider_id,
                    usage=provider_usage or {},
                ),
                estimated_input,
                estimated_output,
            )
        else:
            usage = self._empty_stream_usage()
        cost_usd = self._estimator.cost_usd(usage["billed_input"], usage["billed_output"])
        command = self._build_finalization_command(
            request_id=request_id,
            reservation_id=reservation_id,
            operation=operation,
            client=client,
            endpoint=endpoint,
            profile_id=profile_id,
            provider=provider,
            usage=usage,
            estimated_input=estimated_input,
            estimated_output=estimated_output,
            cost_usd=cost_usd,
            content=content,
            budget_before=budget_before,
            duration_ms=duration_ms,
            attempts=attempts,
            trace=trace,
            replay_payload=replay_payload,
            status=status,
            status_code=status_code,
            error_code=error_code,
            error_message=error_message,
        )
        try:
            receipt = await self._submit_finalization(command)
            return _StreamFinalization(receipt=receipt, usage=usage)
        except FinalizationRejectedError as exc:
            if operation != "settle":
                raise StreamFinalizationUnknownError(request_id=request_id) from exc

        accounting_error = BudgetSettlementExceededError(request_id=request_id)
        released_usage = self._empty_stream_usage()
        release_command = self._build_finalization_command(
            request_id=request_id,
            reservation_id=reservation_id,
            operation="release",
            client=client,
            endpoint=endpoint,
            profile_id=profile_id,
            provider=provider,
            usage=released_usage,
            estimated_input=estimated_input,
            estimated_output=estimated_output,
            cost_usd=0.0,
            content=content,
            budget_before=budget_before,
            duration_ms=duration_ms,
            attempts=attempts,
            trace=[
                *trace,
                DecisionStep(
                    step="accounting_failed",
                    reason=accounting_error.error_code,
                    meta={"settlement_rejected": True},
                ),
            ],
            replay_payload=replay_payload,
            status="accounting_failed",
            status_code=http_status_for(accounting_error.error_code),
            error_code=accounting_error.error_code,
            error_message=str(accounting_error),
        )
        receipt = await self._submit_finalization(release_command)
        return _StreamFinalization(
            receipt=receipt,
            usage=released_usage,
            accounting_error=accounting_error,
        )

    def _build_finalization_command(
        self,
        *,
        request_id: str,
        reservation_id: str,
        operation: Literal["settle", "release"],
        client: ClientConfig,
        endpoint: str,
        profile_id: str,
        provider: ProviderPort | None,
        usage: dict[str, Any],
        estimated_input: int,
        estimated_output: int,
        cost_usd: float,
        content: str,
        budget_before: int,
        duration_ms: int,
        attempts: list[ProviderAttempt],
        trace: list[DecisionStep],
        replay_payload: dict[str, Any],
        status: str,
        status_code: int,
        error_code: str | None,
        error_message: str | None,
    ) -> FinalizeStreamCommand:
        row, attempt_rows = self._log_service.build_stream_record(
            request_id=request_id,
            client_id=client.client_id,
            model_profile=profile_id,
            endpoint=endpoint,
            selected_provider=provider.provider_id if provider is not None else None,
            status=status,
            status_code=status_code,
            usage=usage,
            estimated_input=estimated_input,
            estimated_output=estimated_output,
            estimated_cost_usd=cost_usd,
            budget_before=budget_before,
            duration_ms=duration_ms,
            attempts=attempts,
            decision_trace=[step.to_dict() for step in trace],
            replay_payload=replay_payload,
            response_content=content,
            error_code=error_code,
            error_message=error_message,
        )
        tokens = int(usage["billed_input"]) + int(usage["billed_output"])
        payload = {
            "reservation_id": reservation_id,
            "request_id": request_id,
            "operation": operation,
            "tokens": tokens,
            "cost_usd": cost_usd,
            "request_row": row,
            "attempts": attempt_rows,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return FinalizeStreamCommand(
            reservation_id=reservation_id,
            request_id=request_id,
            operation=operation,
            tokens=tokens,
            cost_usd=cost_usd,
            payload_fingerprint=fingerprint,
            request_row=row,
            attempts=attempt_rows,
        )

    async def _submit_finalization(self, command: FinalizeStreamCommand) -> FinalizationReceipt:
        try:
            with self._phase("audit.persist.duration"):
                return await self._blocking_io.run(
                    self._stream_finalizer.finalize_stream,
                    command,
                    dependency="database",
                )
        except FinalizationRejectedError:
            raise
        except FinalizationConflictError as exc:
            raise StreamFinalizationUnknownError(request_id=command.request_id) from exc
        except Exception as exc:
            try:
                receipt = await self._blocking_io.run(
                    self._stream_finalizer.get_finalization,
                    command.reservation_id,
                    dependency="database",
                    recovery_probe=True,
                )
            except Exception as query_exc:
                raise StreamFinalizationUnknownError(request_id=command.request_id) from query_exc
            if (
                receipt is not None
                and receipt.request_id == command.request_id
                and receipt.operation == command.operation
                and receipt.payload_fingerprint == command.payload_fingerprint
            ):
                return receipt
            raise StreamFinalizationUnknownError(request_id=command.request_id) from exc

    @staticmethod
    def _empty_stream_usage() -> dict[str, Any]:
        return {
            "billed_input": 0,
            "billed_output": 0,
            "actual_input": None,
            "actual_output": None,
            "source": "not_billed",
        }

    @staticmethod
    def _stream_error_event(exc: BaseException, request_id: str) -> StreamEvent:
        return StreamEvent(
            event="error",
            data={
                "code": getattr(exc, "error_code", "provider_failed"),
                "message": "stream terminated",
                "request_id": request_id,
            },
        )

    def _handle_stream_candidate_failure(
        self,
        exc: Exception,
        attempt: ProviderAttempt,
        attempt_started: float,
        circuit: CircuitBreaker | None,
        attempts: list[ProviderAttempt],
        trace: list[DecisionStep],
        first_token_sent: bool,
    ) -> None:
        """Record a failed stream attempt before deciding whether it may fall back."""
        error_code = getattr(exc, "error_code", "provider_failed")
        attempt.status = {
            "provider_timeout": "timeout",
            "provider_bad_status": "bad_status",
        }.get(error_code, "error")
        attempt.error_code = error_code
        attempt.error_message = str(exc)
        attempt.latency_ms = int((time.monotonic() - attempt_started) * 1000)
        attempts.append(attempt)
        # Stream policy shares FailurePolicy with buffered fallback. The circuit
        # records provider failures even after first token, while the caller
        # prevents an unsafe switch once output has been released.
        if circuit is not None and error_code in {
            "provider_timeout",
            "provider_failed",
            "provider_bad_status",
        }:
            circuit.record_failure()
        trace.append(
            DecisionStep(
                step="provider_stream_failed",
                reason=error_code,
                meta={
                    "provider": attempt.provider_id,
                    "attempt_order": attempt.attempt_order,
                    "after_first_token": first_token_sent,
                },
            )
        )

    def _stream_can_fallback(self, exc: Exception, profile_id: str) -> bool:
        profile = self._profiles[profile_id]
        error_code = getattr(exc, "error_code", "provider_failed")
        return self._fallback.decide_failure(error_code, profile.fallback.trigger_on).fallbackable

    async def _serve_cache_hit(
        self,
        cached: ChatResponse,
        request_id: str,
        client: ClientConfig,
        profile_id: str,
        endpoint: str,
        estimated_input: int,
        cache_key: str,
        start: float,
        trace: list[DecisionStep],
        replay_payload: dict[str, Any],
    ) -> ChatOutcome:
        content = cached.content
        estimated_output = self._estimator.estimate_text(content)
        estimated_total = estimated_input + estimated_output
        cost_saved = self._estimator.cost_usd(estimated_input, estimated_output)
        duration_ms = int((time.monotonic() - start) * 1000)
        self._metrics.cache_hits.inc()
        self._metrics.cost_saved.inc(cost_saved)
        trace.append(
            DecisionStep(
                step="cache_hit",
                reason="exact governed response match",
                meta={"key": cache_key, "cost_saved_usd": cost_saved},
            )
        )
        await self._blocking_io.run(self._log_service.record_success,
            request_id=request_id,
            client_id=client.client_id,
            model_profile=profile_id,
            endpoint=endpoint,
            selected_provider=cached.provider_id,
            fallback_used=False,
            status_code=200,
            input_tokens=estimated_input,
            output_tokens=estimated_output,
            estimated_tokens=estimated_total,
            estimated_cost_usd=0.0,
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=estimated_output,
            usage_source="cache",
            cost_saved_usd=cost_saved,
            budget_before=None,
            budget_after=None,
            duration_ms=duration_ms,
            attempts=[],
            request_body=replay_payload,
            response_body={"content": content},
            decision_trace=[s.to_dict() for s in trace],
            replay_payload=replay_payload,
            cache_hit=True,
            cache_key=cache_key,
            dependency="database",
        )
        self._metrics.record_request(endpoint, "success", duration_ms / 1000.0)
        self.sync_circuit_metrics()
        return ChatOutcome(
            request_id=request_id,
            content=content,
            provider_id=cached.provider_id,
            model=cached.model or cached.provider_id,
            attempts=[],
            decision_trace=[s.to_dict() for s in trace],
            input_tokens=estimated_input,
            output_tokens=estimated_output,
            estimated_tokens=estimated_total,
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=estimated_output,
            usage_source="cache",
            estimated_cost_usd=0.0,
            cost_saved_usd=cost_saved,
            fallback_used=False,
            cache_hit=True,
            cache_key=cache_key,
            duration_ms=duration_ms,
        )

    async def replay(
        self,
        request: ChatRequest,
        profile_id: str,
        *,
        recorded_attempts: list[dict[str, Any]] | None = None,
        mode: str = "offline",
    ) -> dict[str, Any]:
        """Replay routing without side effects; live provider calls require explicit opt-in."""
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise ModelProfileNotFoundError(profile_id)
        with self._tracer.span("routing.resolve", {"profile": profile.profile_id, "replay": True}):
            candidates = self._routing.resolve_candidates(profile)

        if mode == "offline":
            if not recorded_attempts:
                raise ReplayUnavailableError("Offline replay requires persisted provider attempts")
            by_provider: dict[str, list[dict[str, Any]]] = {}
            for attempt in recorded_attempts:
                by_provider.setdefault(str(attempt.get("provider_id", "")), []).append(attempt)
            simulated: list[dict[str, Any]] = []
            selected = ""
            active_candidates = candidates[:1] if not profile.fallback.enabled else candidates
            for candidate in active_candidates:
                candidate_attempts = by_provider.get(candidate, [])
                if not candidate_attempts:
                    simulated.append(
                        {"provider_id": candidate, "status": "unobserved", "retry_index": 0}
                    )
                    continue
                for attempt in candidate_attempts:
                    item = {
                        "provider_id": candidate,
                        "status": attempt.get("status", "error"),
                        "retry_index": int(attempt.get("retry_index", 0)),
                    }
                    simulated.append(item)
                    if item["status"] == "success":
                        selected = candidate
                        break
                if selected:
                    break
            return {
                "profile": profile_id,
                "selected_provider": selected or None,
                "fallback_used": bool(selected and candidates and selected != candidates[0]),
                "attempts": simulated,
                "mode": "offline",
            }

        if mode != "live":
            raise ReplayUnavailableError(f"Unknown replay mode '{mode}'")
        if not self._config.replay.allow_live:
            raise ReplayUnavailableError(
                "Live replay is disabled; set replay.allow_live=true to opt in"
            )
        response, attempts = await self._fallback.execute(request, profile, candidates)
        return {
            "profile": profile_id,
            "selected_provider": response.provider_id,
            "fallback_used": any(a.status != "success" for a in attempts),
            "attempts": [
                {
                    "provider_id": a.provider_id,
                    "status": a.status,
                    "retry_index": a.retry_index,
                }
                for a in attempts
            ],
            "mode": "live",
        }

    @staticmethod
    def _resolve_usage(
        response: ChatResponse,
        estimated_input: int,
        estimated_output: int,
    ) -> dict[str, Any]:
        """Use provider usage only when the complete reported shape is trustworthy.

        A provider can omit usage entirely, but it must not make a request
        appear cheaper by sending partial, negative, non-integral, or
        self-contradictory counters.  Those cases deliberately fall back to
        the bounded local estimate and retain a distinct audit source.
        """
        usage = response.usage if isinstance(response.usage, dict) else {}
        estimated_input = max(0, int(estimated_input))
        estimated_output = max(0, int(estimated_output))
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        present = {key: key in usage for key in keys}

        def read(key: str) -> int | None:
            value = usage.get(key)
            if isinstance(value, bool) or not isinstance(value, int):
                return None
            if value < 0 or value > _MAX_PROVIDER_USAGE_TOKENS:
                return None
            return value

        if present["prompt_tokens"] or present["completion_tokens"]:
            prompt = read("prompt_tokens")
            completion = read("completion_tokens")
            total = read("total_tokens") if present["total_tokens"] else None
            if (
                prompt is not None
                and completion is not None
                and (total is None or total == prompt + completion)
            ):
                return {
                    "billed_input": prompt,
                    "billed_output": completion,
                    "actual_input": prompt,
                    "actual_output": completion,
                    "source": "provider",
                }
            return ChatService._estimated_usage(estimated_input, estimated_output, invalid=True)

        if present["total_tokens"]:
            total = read("total_tokens")
            if total is not None:
                billed_input = min(estimated_input, total)
                return {
                    "billed_input": billed_input,
                    "billed_output": total - billed_input,
                    "actual_input": None,
                    "actual_output": None,
                    "source": "provider_total",
                }
            return ChatService._estimated_usage(estimated_input, estimated_output, invalid=True)

        return ChatService._estimated_usage(estimated_input, estimated_output, invalid=False)

    @staticmethod
    def _estimated_usage(
        estimated_input: int, estimated_output: int, *, invalid: bool
    ) -> dict[str, Any]:
        return {
            "billed_input": estimated_input,
            "billed_output": estimated_output,
            "actual_input": None,
            "actual_output": None,
            "source": "estimated_invalid_provider_usage" if invalid else "estimated",
        }

    def _enforce_streaming(self, request: ChatRequest, request_id: str) -> None:
        if (
            request.stream
            and not self._config.streaming.enabled
            and self._config.streaming.behavior_if_requested == "reject"
        ):
            raise StreamingNotSupportedError(request_id=request_id)

    def _enforce_rate_limit(self, client: ClientConfig, request_id: str) -> None:
        result = self._rate_limiter.check(client.client_id, client.rate_limit.requests_per_minute)
        if not result.allowed:
            error = RateLimitExceededError(
                message=(
                    f"Rate limit exceeded for client '{client.client_id}' "
                    f"({client.rate_limit.requests_per_minute}/min)"
                ),
                request_id=request_id,
            )
            error.retry_after_ms = result.retry_after_ms  # type: ignore[attr-defined]
            raise error

    @staticmethod
    def _is_database_unavailable(exc: BaseException) -> bool:
        if isinstance(exc, BlockingIOOverloadedError):
            return True
        module = type(exc).__module__
        return module.startswith(("psycopg", "sqlite3"))

    def _resolve_profile(self, request: ChatRequest, request_id: str) -> tuple[ModelProfile, str]:
        profile_id = request.profile or self._config.gateway.default_profile
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise ModelProfileNotFoundError(profile_id, request_id=request_id)
        return profile, profile_id

    def _enforce_guardrails_input(self, request: ChatRequest, request_id: str) -> None:
        combined = "\n".join(message.content for message in request.messages)
        aggregate = self._guardrails.check_input(combined)
        if not aggregate.allowed:
            raise GuardrailBlockedError(
                message=f"Input blocked ({aggregate.reason})", request_id=request_id
            )
        for message in request.messages:
            decision = self._guardrails.check_input(message.content)
            if not decision.allowed:
                raise GuardrailBlockedError(
                    message=f"Input blocked ({decision.reason})", request_id=request_id
                )

    def _enforce_guardrails_output(self, response: ChatResponse, request_id: str) -> str:
        decision = self._guardrails.check_output(response.content)
        if not decision.allowed:
            raise GuardrailBlockedError(
                message=f"Output blocked ({decision.reason})", request_id=request_id
            )
        return decision.content if decision.content is not None else response.content

    def _build_provider_trace(
        self, candidates: list[str], attempts: list[ProviderAttempt]
    ) -> list[DecisionStep]:
        priority = {pid: idx + 1 for idx, pid in enumerate(candidates)}
        steps: list[DecisionStep] = []
        for attempt in attempts:
            pid = attempt.provider_id
            if attempt.status == "success":
                reason = (
                    f"primary candidate (priority={priority.get(pid, 'unknown')})"
                    if attempt.attempt_order == 0
                    else f"fallback after {attempt.attempt_order} failed candidate(s)"
                )
                steps.append(DecisionStep(step="provider_selected", provider=pid, reason=reason))
            elif attempt.status == "circuit_open":
                steps.append(
                    DecisionStep(
                        step="provider_skipped", provider=pid, reason="circuit breaker open"
                    )
                )
            else:
                meta: dict[str, Any] = {"error_code": attempt.error_code}
                if attempt.retry_index:
                    meta["retry_index"] = attempt.retry_index
                steps.append(
                    DecisionStep(
                        step="provider_failed",
                        provider=pid,
                        reason=attempt.status,
                        meta=meta,
                    )
                )
        return steps

    def _record_success_metrics(
        self,
        endpoint: str,
        client: ClientConfig,
        input_tokens: int,
        output_tokens: int,
        attempts: list[ProviderAttempt],
        fallback_used: bool,
        duration_ms: int,
    ) -> None:
        self._metrics.record_request(endpoint, "success", duration_ms / 1000.0)
        self._metrics.record_tokens(client.client_id, "input", input_tokens)
        self._metrics.record_tokens(client.client_id, "output", output_tokens)
        if fallback_used:
            self._metrics.fallbacks.inc()
        for attempt in attempts:
            self._metrics.record_attempt(attempt.provider_id, attempt.status, attempt.latency_ms)
            if attempt.retry_index:
                self._metrics.retries.inc()

    def _record_error_metrics(self, exc: GatewayError, endpoint: str, duration_ms: int) -> None:
        self._metrics.record_request(endpoint, exc.error_code, duration_ms / 1000.0)
        if exc.error_code == "rate_limit_exceeded":
            self._metrics.rate_limited.inc()
        elif exc.error_code == "rate_limit_backend_unavailable":
            self._metrics.redis_failures.inc()
        elif exc.error_code == "token_budget_exceeded":
            self._metrics.budget_exceeded.inc()
        elif exc.error_code == "guardrail_blocked":
            self._metrics.guardrail_blocks.inc()

    def sync_circuit_metrics(self) -> None:
        for provider_id, breaker in self._circuit_breakers.items():
            value = _CIRCUIT_STATE_VALUE.get(breaker.state, 0)
            self._metrics.record_circuit_state(provider_id, value)

    @staticmethod
    def _attempts_from_error(
        exc: GatewayError, attempts: list[ProviderAttempt]
    ) -> list[ProviderAttempt]:
        return getattr(exc, "attempts", attempts) or attempts

    def _release_flight(self, flight: tuple[str, asyncio.Event] | None) -> None:
        if flight is not None:
            self._singleflight.release(*flight)

    async def _cache_get(
        self, cache_key: str, trace: list[DecisionStep]
    ) -> ChatResponse | None:
        """Read cache with explicit Redis fail-open semantics."""
        assert self._cache is not None
        try:
            with self._phase("cache.lookup.duration"):
                return await self._blocking_io.run(self._cache.get, cache_key)
        except Exception:
            if self._distributed_singleflight is None:
                raise
            self._metrics.redis_failures.inc()
            trace.append(DecisionStep(step="cache_degraded", reason="redis_unavailable"))
            return None

    @contextmanager
    def _phase(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
        """Keep stage timings consistent in local traces and Prometheus metrics."""
        started = time.monotonic()
        try:
            with self._tracer.span(name, attributes) as span:
                yield span
        finally:
            self._metrics.record_phase(name, time.monotonic() - started)

    async def _cache_put(
        self, cache_key: str, response: ChatResponse, trace: list[DecisionStep]
    ) -> None:
        """Cache publication is advisory: a Redis outage must not fail a chat."""
        assert self._cache is not None
        try:
            await self._blocking_io.run(self._cache.put, cache_key, response)
        except Exception:
            if self._distributed_singleflight is None:
                raise
            self._metrics.redis_failures.inc()
            trace.append(DecisionStep(step="cache_degraded", reason="redis_unavailable"))

    async def _acquire_distributed_flight(
        self,
        cache_key: str,
        deadline_at: float,
        trace: list[DecisionStep],
    ) -> str | None:
        """Acquire a global lease or wait with bounded backoff for cache fill."""
        if self._distributed_singleflight is None:
            return None
        delay_s = 0.025
        while True:
            try_acquire = self._distributed_singleflight.try_acquire
            acquired = await self._blocking_io.run(try_acquire, cache_key)
            if acquired is True:
                trace.append(DecisionStep(step="distributed_singleflight_owner"))
                return cache_key
            if acquired is None:
                self._metrics.redis_failures.inc()
                trace.append(
                    DecisionStep(
                        step="distributed_singleflight_degraded",
                        reason="redis_unavailable; using local singleflight",
                    )
                )
                return None
            trace.append(
                DecisionStep(
                    step="distributed_singleflight_wait",
                    reason="another replica owns the cache-miss lease",
                )
            )
            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                raise RequestDeadlineExceededError()
            await asyncio.sleep(min(delay_s, remaining))
            delay_s = min(delay_s * 2, 0.25)
            cached = await self._cache_get(cache_key, trace)
            if cached is not None:
                return None

    async def _release_distributed_flight(self, cache_key: str | None) -> None:
        if cache_key is not None and self._distributed_singleflight is not None:
            released = await self._blocking_io.run(
                self._distributed_singleflight.release, cache_key
            )
            if released is None:
                self._metrics.redis_failures.inc()

    @staticmethod
    def _request_body_snapshot(request: ChatRequest) -> dict[str, Any]:
        return {
            "profile": request.profile,
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content} for message in request.messages
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": request.stream,
        }
