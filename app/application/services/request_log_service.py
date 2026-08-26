"""Persists request logs and provider attempts for auditing."""

from __future__ import annotations

import json
from typing import Any

from app.domain.models.provider import ProviderAttempt
from app.domain.ports.repositories import RequestLogRepositoryPort
from app.infrastructure.config.config_models import LoggingConfig


class RequestLogService:
    def __init__(self, repository: RequestLogRepositoryPort, config: LoggingConfig) -> None:
        self._repo = repository
        self._config = config

    def record_success(
        self,
        *,
        request_id: str,
        client_id: str,
        model_profile: str,
        endpoint: str,
        selected_provider: str,
        fallback_used: bool,
        status_code: int,
        input_tokens: int,
        output_tokens: int,
        estimated_tokens: int,
        estimated_cost_usd: float,
        estimated_input_tokens: int | None = None,
        estimated_output_tokens: int | None = None,
        actual_input_tokens: int | None = None,
        actual_output_tokens: int | None = None,
        usage_source: str = "estimated",
        budget_before: int | None,
        budget_after: int | None,
        duration_ms: int,
        attempts: list[ProviderAttempt],
        request_body: Any = None,
        response_body: Any = None,
        decision_trace: list[dict[str, Any]] | None = None,
        replay_payload: Any = None,
        cache_hit: bool = False,
        cache_key: str = "",
        cost_saved_usd: float = 0.0,
    ) -> None:
        row = {
            "request_id": request_id,
            "client_id": client_id,
            "model_profile": model_profile,
            "endpoint": endpoint,
            "selected_provider": selected_provider,
            "fallback_used": 1 if fallback_used else 0,
            "status": "success",
            "status_code": status_code,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_input_tokens": (
                input_tokens if estimated_input_tokens is None else estimated_input_tokens
            ),
            "estimated_output_tokens": (
                output_tokens if estimated_output_tokens is None else estimated_output_tokens
            ),
            "actual_input_tokens": actual_input_tokens,
            "actual_output_tokens": actual_output_tokens,
            "usage_source": usage_source,
            "estimated_tokens": estimated_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "cost_saved_usd": cost_saved_usd,
            "budget_before": budget_before,
            "budget_after": budget_after,
            "duration_ms": duration_ms,
            "error_code": None,
            "error_message": None,
            "cache_hit": 1 if cache_hit else 0,
            "cache_key": cache_key or None,
            "decision_trace": self._serialize(decision_trace) if decision_trace else None,
            "replay_payload": self._serialize(replay_payload)
            if self._config.persist_replay_payload
            else None,
            "request_body": self._serialize(request_body)
            if self._config.persist_request_body
            else None,
            "response_body": self._serialize(response_body)
            if self._config.persist_response_body
            else None,
        }
        attempt_rows = (
            [self._attempt_row(request_id, attempt) for attempt in attempts]
            if self._config.persist_attempts
            else []
        )
        self._repo.insert_request_with_attempts(row, attempt_rows)

    def record_error(
        self,
        *,
        request_id: str,
        client_id: str,
        model_profile: str | None,
        endpoint: str,
        status_code: int,
        error_code: str,
        error_message: str,
        duration_ms: int,
        attempts: list[ProviderAttempt] | None = None,
        request_body: Any = None,
        decision_trace: list[dict[str, Any]] | None = None,
        replay_payload: Any = None,
    ) -> None:
        row = {
            "request_id": request_id,
            "client_id": client_id,
            "model_profile": model_profile,
            "endpoint": endpoint,
            "selected_provider": None,
            "fallback_used": 0,
            "status": "error",
            "status_code": status_code,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "actual_input_tokens": None,
            "actual_output_tokens": None,
            "usage_source": "estimated",
            "estimated_tokens": 0,
            "estimated_cost_usd": 0.0,
            "cost_saved_usd": 0.0,
            "budget_before": None,
            "budget_after": None,
            "duration_ms": duration_ms,
            "error_code": error_code,
            "error_message": error_message,
            "cache_hit": 0,
            "cache_key": None,
            "decision_trace": self._serialize(decision_trace) if decision_trace else None,
            "replay_payload": self._serialize(replay_payload)
            if self._config.persist_replay_payload
            else None,
            "request_body": self._serialize(request_body)
            if self._config.persist_request_body
            else None,
            "response_body": None,
        }
        attempt_rows = (
            [self._attempt_row(request_id, attempt) for attempt in attempts or []]
            if self._config.persist_attempts
            else []
        )
        self._repo.insert_request_with_attempts(row, attempt_rows)

    def record_http_error(
        self,
        *,
        request_id: str,
        endpoint: str,
        status_code: int,
        error_code: str,
        client_id: str = "",
        error_message: str = "",
    ) -> None:
        """Persist failures that happen outside ChatService (auth/validation/routing)."""
        self.record_error(
            request_id=request_id,
            client_id=client_id,
            model_profile=None,
            endpoint=endpoint,
            status_code=status_code,
            error_code=error_code,
            error_message=error_message,
            duration_ms=0,
        )

    def get(self, request_id: str) -> dict[str, Any] | None:
        return self._repo.get_request(request_id)

    @staticmethod
    def _attempt_row(request_id: str, attempt: ProviderAttempt) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "provider_id": attempt.provider_id,
            "attempt_order": attempt.attempt_order,
            "retry_index": attempt.retry_index,
            "status": attempt.status,
            "status_code": attempt.status_code,
            "latency_ms": attempt.latency_ms,
            "error_code": attempt.error_code,
            "error_message": attempt.error_message,
        }

    @staticmethod
    def _serialize(value: Any) -> str | None:
        if value is None:
            return None
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
