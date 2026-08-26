"""Single decision point for retry, fallback, and circuit-breaker effects."""

from __future__ import annotations

from dataclasses import dataclass

_TRIGGER_ALIASES = {
    "provider_error": "provider_failed",
    "timeout": "provider_timeout",
    "bad_status": "provider_bad_status",
}


@dataclass(frozen=True)
class FailureDecision:
    retryable: bool
    fallbackable: bool
    affects_circuit: bool


class FailurePolicy:
    def __init__(self, retry_on: list[str] | tuple[str, ...]) -> None:
        self._retry_on = {self.normalize(value) for value in retry_on}

    @staticmethod
    def normalize(value: str) -> str:
        return _TRIGGER_ALIASES.get(value, value)

    def decide(self, error_code: str, fallback_on: list[str]) -> FailureDecision:
        code = self.normalize(error_code)
        configured_fallback = {self.normalize(value) for value in fallback_on}
        provider_failure = code in {
            "provider_timeout",
            "provider_failed",
            "provider_bad_status",
        }
        skip_failure = code in {"circuit_open", "provider_not_found"}
        # Empty fallback trigger list retains the legacy "all provider failures" behavior.
        fallbackable = skip_failure or (
            provider_failure and (not configured_fallback or code in configured_fallback)
        )
        return FailureDecision(
            retryable=provider_failure and code in self._retry_on,
            fallbackable=fallbackable,
            affects_circuit=provider_failure,
        )
