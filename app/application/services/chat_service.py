"""Correctness-first orchestration for the gateway data plane."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import replace
from typing import Any

from app.application.dto.chat_dto import AttemptDetail, ChatOutcome
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
    GatewayError,
    GuardrailBlockedError,
    InternalError,
    ModelProfileNotFoundError,
    RateLimitExceededError,
    ReplayUnavailableError,
    RequestDeadlineExceededError,
    StreamingNotSupportedError,
    http_status_for,
)
from app.domain.models.decision_trace import DecisionStep
from app.domain.models.model_profile import ModelProfile
from app.domain.models.provider import ProviderAttempt
from app.domain.ports.provider_port import ChatRequest, ChatResponse, ProviderPort
from app.domain.ports.repositories import PromptCachePort, RateLimiterPort
from app.infrastructure.config.config_models import AppConfig, ClientConfig
from app.infrastructure.observability.gateway_metrics import GatewayMetrics
from app.infrastructure.observability.tracing import TraceRecorder

_CIRCUIT_STATE_VALUE = {
    CircuitState.CLOSED: 0,
    CircuitState.OPEN: 1,
    CircuitState.HALF_OPEN: 2,
}


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
        metrics: GatewayMetrics,
        cache: PromptCachePort | None = None,
        singleflight: SingleFlight | None = None,
        distributed_singleflight: Any | None = None,
        tracer: TraceRecorder | None = None,
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
        self._metrics = metrics
        self._cache = cache
        self._cache_enabled = config.cache.enabled and cache is not None
        self._singleflight = singleflight or SingleFlight()
        self._distributed_singleflight = distributed_singleflight
        self._tracer = tracer or TraceRecorder(enabled=False)

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

        try:
            self._enforce_streaming(request, request_id)
            trace.append(DecisionStep(step="streaming_checked", meta={"allowed": True}))

            self._enforce_rate_limit(client, request_id)
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

            cached = self._cache_get(cache_key, trace) if self._cache_enabled else None
            if cached is not None:
                return self._serve_cache_hit(
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
                        await asyncio.wait_for(event.wait(), timeout=remaining)
                    except TimeoutError as exc:
                        raise RequestDeadlineExceededError(request_id=request_id) from exc
                    cached = self._cache_get(cache_key, trace)
                    if cached is not None:
                        return self._serve_cache_hit(
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
                cached = self._cache_get(cache_key, trace)
                if cached is not None:
                    self._release_distributed_flight(distributed_flight_key)
                    distributed_flight_key = None
                    self._release_flight(flight)
                    flight = None
                    return self._serve_cache_hit(
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

            budget_before = self._budget.snapshot(client)
            reserved_tokens = estimated_input + max(0, request.max_tokens)
            reserved_cost = self._estimator.cost_usd(estimated_input, max(0, request.max_tokens))
            reservation_id = f"{request_id}:{uuid.uuid4().hex}"
            reserved = self._budget.reserve(
                reservation_id,
                client,
                reserved_tokens,
                reserved_cost,
            )
            trace.append(
                DecisionStep(
                    step="budget_reserved",
                    meta={
                        "tokens": reserved_tokens,
                        "remaining_after_reservation": reserved.remaining_tokens,
                    },
                )
            )

            with self._tracer.span(
                "routing.resolve", {"profile": profile.profile_id}
            ) as routing_span:
                candidates = self._routing.resolve_candidates(profile)
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
            budget_after = self._budget.settle(
                reservation_id,
                client,
                billed_input + billed_output,
                cost_usd,
            )
            reservation_id = None
            trace.append(
                DecisionStep(
                    step="budget_settled",
                    meta={
                        "remaining_after": budget_after.remaining_tokens,
                        "usage_source": usage["source"],
                    },
                )
            )

            if self._cache_enabled:
                self._cache_put(cache_key, governed_response, trace)
            self._release_distributed_flight(distributed_flight_key)
            distributed_flight_key = None
            self._release_flight(flight)
            flight = None

            fallback_used = any(a.status != "success" for a in attempts)
            duration_ms = int((time.monotonic() - start) * 1000)
            estimated_total = estimated_input + estimated_output

            self._log_service.record_success(
                request_id=request_id,
                client_id=client.client_id,
                model_profile=profile_id,
                endpoint=endpoint,
                selected_provider=response.provider_id,
                fallback_used=fallback_used,
                status_code=200,
                input_tokens=billed_input,
                output_tokens=billed_output,
                estimated_tokens=estimated_total,
                estimated_cost_usd=cost_usd,
                estimated_input_tokens=estimated_input,
                estimated_output_tokens=estimated_output,
                actual_input_tokens=usage["actual_input"],
                actual_output_tokens=usage["actual_output"],
                usage_source=usage["source"],
                cost_saved_usd=0.0,
                budget_before=budget_before.remaining_tokens,
                budget_after=budget_after.remaining_tokens,
                duration_ms=duration_ms,
                attempts=attempts,
                request_body=replay_payload,
                response_body={"content": content},
                decision_trace=[s.to_dict() for s in trace],
                replay_payload=replay_payload,
                cache_hit=False,
                cache_key=cache_key,
            )

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
                budget_after=budget_after.remaining_tokens,
                fallback_used=fallback_used,
                cache_hit=False,
                cache_key=cache_key,
                duration_ms=duration_ms,
            )

        except GatewayError as exc:
            if reservation_id is not None:
                self._budget.release(reservation_id)
            self._release_distributed_flight(distributed_flight_key)
            self._release_flight(flight)
            attempts = self._attempts_from_error(exc, attempts)
            if attempts and not provider_trace_recorded:
                trace.extend(self._build_provider_trace([], attempts))
            duration_ms = int((time.monotonic() - start) * 1000)
            trace.append(
                DecisionStep(step="error", reason=exc.error_code, meta={"message": str(exc)})
            )
            self._log_service.record_error(
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
            )
            self._record_error_metrics(exc, endpoint, duration_ms)
            self.sync_circuit_metrics()
            raise

        except asyncio.CancelledError:
            if reservation_id is not None:
                self._budget.release(reservation_id)
            self._release_distributed_flight(distributed_flight_key)
            self._release_flight(flight)
            if attempts and not provider_trace_recorded:
                trace.extend(self._build_provider_trace([], attempts))
            duration_ms = int((time.monotonic() - start) * 1000)
            trace.append(DecisionStep(step="error", reason="client_cancelled"))
            self._log_service.record_error(
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
            )
            self._metrics.record_request(endpoint, "client_cancelled", duration_ms / 1000.0)
            self.sync_circuit_metrics()
            raise

        except Exception as exc:
            if reservation_id is not None:
                self._budget.release(reservation_id)
            self._release_distributed_flight(distributed_flight_key)
            self._release_flight(flight)
            duration_ms = int((time.monotonic() - start) * 1000)
            trace.append(
                DecisionStep(step="error", reason="internal_error", meta={"message": str(exc)})
            )
            self._log_service.record_error(
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
            )
            self._metrics.record_request(endpoint, "internal_error", duration_ms / 1000.0)
            self.sync_circuit_metrics()
            raise InternalError(message=str(exc), request_id=request_id) from exc

    def _serve_cache_hit(
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
        self._log_service.record_success(
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
        with self._tracer.span(
            "routing.resolve", {"profile": profile.profile_id, "replay": True}
        ):
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
        usage = response.usage or {}
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or 0)
        if prompt > 0 or completion > 0:
            return {
                "billed_input": prompt,
                "billed_output": completion,
                "actual_input": prompt,
                "actual_output": completion,
                "source": "provider",
            }
        if total > 0:
            billed_input = min(estimated_input, total)
            return {
                "billed_input": billed_input,
                "billed_output": total - billed_input,
                "actual_input": None,
                "actual_output": None,
                "source": "provider_total",
            }
        return {
            "billed_input": estimated_input,
            "billed_output": estimated_output,
            "actual_input": None,
            "actual_output": None,
            "source": "estimated",
        }

    def _enforce_streaming(self, request: ChatRequest, request_id: str) -> None:
        if (
            request.stream
            and not self._config.streaming.enabled
            and self._config.streaming.behavior_if_requested == "reject"
        ):
            raise StreamingNotSupportedError(request_id=request_id)

    def _enforce_rate_limit(self, client: ClientConfig, request_id: str) -> None:
        result = self._rate_limiter.check(
            client.client_id, client.rate_limit.requests_per_minute
        )
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

    def _resolve_profile(
        self, request: ChatRequest, request_id: str
    ) -> tuple[ModelProfile, str]:
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

    def _cache_get(
        self, cache_key: str, trace: list[DecisionStep]
    ) -> ChatResponse | None:
        """Read cache with explicit Redis fail-open semantics."""
        assert self._cache is not None
        try:
            return self._cache.get(cache_key)
        except Exception:
            if self._distributed_singleflight is None:
                raise
            self._metrics.redis_failures.inc()
            trace.append(
                DecisionStep(step="cache_degraded", reason="redis_unavailable")
            )
            return None

    def _cache_put(
        self, cache_key: str, response: ChatResponse, trace: list[DecisionStep]
    ) -> None:
        """Cache publication is advisory: a Redis outage must not fail a chat."""
        assert self._cache is not None
        try:
            self._cache.put(cache_key, response)
        except Exception:
            if self._distributed_singleflight is None:
                raise
            self._metrics.redis_failures.inc()
            trace.append(
                DecisionStep(step="cache_degraded", reason="redis_unavailable")
            )

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
            acquired = self._distributed_singleflight.try_acquire(cache_key)
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
            cached = self._cache_get(cache_key, trace)
            if cached is not None:
                return None

    def _release_distributed_flight(self, cache_key: str | None) -> None:
        if cache_key is not None and self._distributed_singleflight is not None:
            released = self._distributed_singleflight.release(cache_key)
            if released is None:
                self._metrics.redis_failures.inc()

    @staticmethod
    def _request_body_snapshot(request: ChatRequest) -> dict[str, Any]:
        return {
            "profile": request.profile,
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": request.stream,
        }
