"""DTOs returned by the chat orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.models.provider import ProviderAttempt


@dataclass
class AttemptDetail:
    provider_id: str
    attempt_order: int
    retry_index: int
    status: str
    latency_ms: int
    error_code: str = ""
    error_message: str = ""

    @classmethod
    def from_attempt(cls, attempt: ProviderAttempt) -> AttemptDetail:
        return cls(
            provider_id=attempt.provider_id,
            attempt_order=attempt.attempt_order,
            retry_index=attempt.retry_index,
            status=attempt.status,
            latency_ms=attempt.latency_ms,
            error_code=attempt.error_code,
            error_message=attempt.error_message,
        )


@dataclass
class ChatOutcome:
    request_id: str
    content: str
    provider_id: str
    model: str
    attempts: list[AttemptDetail] = field(default_factory=list)
    decision_trace: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_tokens: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    actual_input_tokens: int | None = None
    actual_output_tokens: int | None = None
    usage_source: str = "estimated"
    estimated_cost_usd: float = 0.0
    cost_saved_usd: float = 0.0
    budget_before: int | None = None
    budget_after: int | None = None
    fallback_used: bool = False
    cache_hit: bool = False
    cache_key: str = ""
    duration_ms: int = 0
