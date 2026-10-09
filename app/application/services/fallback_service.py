"""Fallback orchestration with retry and circuit breaking.

Iterates a fallback chain. For each provider it (1) consults the circuit
breaker, (2) attempts the call with retry + exponential backoff on retryable
errors, and (3) records the outcome. Returns the first success or raises
FallbackExhaustedError.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.application.services.circuit_breaker import CircuitBreaker
from app.application.services.failure_policy import FailurePolicy
from app.domain.errors import (
    FallbackExhaustedError,
    ProviderBadStatusError,
    ProviderFailedError,
    ProviderTimeoutError,
    RequestDeadlineExceededError,
)
from app.domain.models.model_profile import ModelProfile
from app.domain.models.provider import ProviderAttempt
from app.domain.ports.provider_port import ChatRequest, ChatResponse, ProviderPort
from app.infrastructure.observability.tracing import TraceRecorder

logger = logging.getLogger(__name__)

_FALLBACK_TRIGGERS = (
    ProviderTimeoutError,
    ProviderFailedError,
    ProviderBadStatusError,
)

_STATUS_BY_ERROR = {
    ProviderTimeoutError: "timeout",
    ProviderFailedError: "error",
    ProviderBadStatusError: "bad_status",
}

_DEFAULT_RETRY_ON = ("provider_timeout", "provider_failed", "provider_bad_status")


class FallbackService:
    """Execute a chat request with fallback across multiple providers."""

    def __init__(
        self,
        provider_registry: dict[str, ProviderPort],
        circuit_breakers: dict[str, CircuitBreaker] | None = None,
        retry_max: int = 0,
        retry_base_delay_ms: int = 50,
        retry_max_delay_ms: int = 1000,
        retry_on: list[str] | tuple[str, ...] = _DEFAULT_RETRY_ON,
        request_timeout_ms: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        tracer: TraceRecorder | None = None,
        metrics: Any | None = None,
    ) -> None:
        self._registry = provider_registry
        self._circuit_breakers = circuit_breakers or {}
        self._retry_max = max(0, retry_max)
        self._retry_base_delay_ms = retry_base_delay_ms
        self._retry_max_delay_ms = retry_max_delay_ms
        self._policy = FailurePolicy(retry_on)
        self._request_timeout_ms = max(1, request_timeout_ms)
        self._clock = clock
        self._sleep = sleeper
        self._tracer = tracer or TraceRecorder(enabled=False)
        self._metrics = metrics

    async def execute(
        self,
        request: ChatRequest,
        profile: ModelProfile,
        candidate_order: list[str],
        deadline_at: float | None = None,
    ) -> tuple[ChatResponse, list[ProviderAttempt]]:
        attempts: list[ProviderAttempt] = []
        deadline_at = deadline_at or self._clock() + self._request_timeout_ms / 1000.0

        if not profile.fallback.enabled:
            candidate_order = candidate_order[:1]

        for idx, provider_id in enumerate(candidate_order):
            provider = self._registry.get(provider_id)
            if provider is None:
                attempts.append(
                    ProviderAttempt(
                        provider_id=provider_id,
                        attempt_order=idx,
                        status="error",
                        error_code="provider_not_found",
                        error_message=f"Provider '{provider_id}' not found in registry",
                    )
                )
                continue

            try:
                response, provider_attempts, can_fallback = await self._try_provider(
                    provider,
                    request,
                    idx,
                    profile.fallback.trigger_on,
                    deadline_at,
                )
            except RequestDeadlineExceededError as exc:
                exc.attempts = attempts + list(getattr(exc, "attempts", []))  # type: ignore[attr-defined]
                raise
            attempts.extend(provider_attempts)

            if response is not None:
                return response, attempts
            if not can_fallback:
                break

            logger.warning(
                "Provider '%s' (attempt %d) exhausted; moving to next candidate",
                provider_id,
                idx,
            )

        error = FallbackExhaustedError(profile_id=profile.profile_id)
        error.attempts = attempts  # type: ignore[attr-defined]
        raise error

    def decide_failure(self, error_code: str, fallback_on: list[str]):
        """Expose the shared failure taxonomy to streaming selection."""
        return self._policy.decide(error_code, fallback_on)

    async def _try_provider(
        self,
        provider: ProviderPort,
        request: ChatRequest,
        order: int,
        fallback_on: list[str],
        deadline_at: float,
    ) -> tuple[ChatResponse | None, list[ProviderAttempt], bool]:
        attempts: list[ProviderAttempt] = []
        circuit = self._circuit_breakers.get(provider.provider_id)

        for retry_index in range(self._retry_max + 1):
            if self._remaining(deadline_at) <= 0:
                error = RequestDeadlineExceededError()
                error.attempts = attempts  # type: ignore[attr-defined]
                raise error
            if circuit is not None and not circuit.allow_request():
                attempts.append(
                    ProviderAttempt(
                        provider_id=provider.provider_id,
                        attempt_order=order,
                        status="circuit_open",
                        error_code="circuit_open",
                        error_message="circuit breaker is open",
                        retry_index=retry_index,
                    )
                )
                return None, attempts, True

            # Providers are invoked directly today, so queue wait is intentionally
            # measured as the time to enter the call rather than inventing a queue.
            # A future bounded provider pool can keep this span and report a real wait.
            queue_started = self._clock()
            with self._tracer.span(
                "provider.queue_wait",
                {"provider": provider.provider_id, "queueing": False},
            ):
                pass
            self._record_phase("provider.queue_wait", self._clock() - queue_started)
            provider_started = self._clock()
            with self._tracer.span(
                "provider.duration",
                {"provider": provider.provider_id, "retry_index": retry_index},
            ) as duration_span:
                with self._tracer.span(
                    "provider.attempt",
                    {"provider": provider.provider_id, "retry_index": retry_index},
                ) as attempt_span:
                    response, attempt = await self._call_provider(
                        provider, request, order, retry_index, deadline_at
                    )
                    attempt_span.attributes["status"] = attempt.status
                duration_span.attributes["status"] = attempt.status
            self._record_phase("provider.duration", self._clock() - provider_started)
            attempts.append(attempt)

            decision = self._policy.decide(attempt.error_code, fallback_on)
            if circuit is not None:
                if attempt.status == "success":
                    circuit.record_success()
                elif decision.affects_circuit:
                    circuit.record_failure()

            if attempt.status == "success":
                return response, attempts, True

            should_retry = retry_index < self._retry_max and decision.retryable
            if not should_retry:
                return None, attempts, decision.fallbackable

            delay = self._backoff_ms(retry_index) / 1000.0
            remaining = self._remaining(deadline_at)
            if remaining <= delay:
                error = RequestDeadlineExceededError()
                error.attempts = attempts  # type: ignore[attr-defined]
                raise error
            await self._sleep(delay)

        return None, attempts, True

    async def _call_provider(
        self,
        provider: ProviderPort,
        request: ChatRequest,
        order: int,
        retry_index: int,
        deadline_at: float,
    ) -> tuple[ChatResponse | None, ProviderAttempt]:
        start = self._clock()
        try:
            remaining = self._remaining(deadline_at)
            if remaining <= 0:
                raise TimeoutError
            response = await asyncio.wait_for(provider.chat(request), timeout=remaining)
            latency_ms = int((self._clock() - start) * 1000)
            attempt = ProviderAttempt(
                provider_id=provider.provider_id,
                attempt_order=order,
                status="success",
                latency_ms=latency_ms,
                status_code=200,
                retry_index=retry_index,
                response={
                    "content": response.content,
                    "provider_id": response.provider_id,
                    "model": response.model,
                },
                provider_request_id=response.metadata.get("provider_request_id", ""),
            )
            return response, attempt
        except TimeoutError:
            latency_ms = int((self._clock() - start) * 1000)
            attempt = ProviderAttempt(
                provider_id=provider.provider_id,
                attempt_order=order,
                status="timeout",
                latency_ms=latency_ms,
                error_code="provider_timeout",
                error_message="overall request deadline exhausted during provider call",
                retry_index=retry_index,
            )
            return None, attempt
        except _FALLBACK_TRIGGERS as exc:
            latency_ms = int((self._clock() - start) * 1000)
            status = _STATUS_BY_ERROR.get(type(exc), "error")
            attempt = ProviderAttempt(
                provider_id=provider.provider_id,
                attempt_order=order,
                status=status,
                latency_ms=latency_ms,
                error_code=getattr(exc, "error_code", "error"),
                error_message=str(exc),
                retry_index=retry_index,
            )
            return None, attempt
        except Exception as exc:  # unexpected provider error — record it and keep falling back
            # asyncio.CancelledError is a BaseException, so it still propagates here.
            latency_ms = int((self._clock() - start) * 1000)
            logger.exception(
                "Provider '%s' raised an unexpected error; treating as a failed attempt",
                provider.provider_id,
            )
            attempt = ProviderAttempt(
                provider_id=provider.provider_id,
                attempt_order=order,
                status="error",
                latency_ms=latency_ms,
                error_code="provider_failed",
                error_message=f"unexpected error: {exc}",
                retry_index=retry_index,
            )
            return None, attempt

    def _backoff_ms(self, retry_index: int) -> int:
        base = self._retry_base_delay_ms * (2**retry_index)
        base = min(base, self._retry_max_delay_ms)
        jitter = random.uniform(0.8, 1.2)
        return int(base * jitter)

    def _remaining(self, deadline_at: float) -> float:
        return max(0.0, deadline_at - self._clock())

    def _record_phase(self, phase: str, duration_s: float) -> None:
        if self._metrics is not None:
            self._metrics.record_phase(phase, duration_s)
