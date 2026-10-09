"""Domain-level errors for the LLM Gateway."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorLayer(Enum):
    GATEWAY = "gateway"
    PROVIDER = "provider"


@dataclass
class GatewayError(Exception):
    """Base structured error for the gateway."""

    error_code: str
    message: str
    request_id: str = ""
    retryable: bool = False
    error_layer: ErrorLayer = ErrorLayer.GATEWAY

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message}"


# ── Gateway-level errors ──


class AuthFailedError(GatewayError):
    def __init__(self, message: str = "Authentication failed", **kwargs: object) -> None:
        super().__init__(error_code="auth_failed", message=message, **kwargs)


class RateLimitExceededError(GatewayError):
    def __init__(self, message: str = "Rate limit exceeded", **kwargs: object) -> None:
        super().__init__(error_code="rate_limit_exceeded", message=message, **kwargs)


class RateLimitBackendUnavailableError(GatewayError):
    """Fail-closed response when the shared rate-limit authority is down."""

    def __init__(self, message: str = "Rate-limit backend unavailable", **kwargs: object) -> None:
        super().__init__(
            error_code="rate_limit_backend_unavailable",
            message=message,
            retryable=True,
            **kwargs,
        )


class TokenBudgetExceededError(GatewayError):
    def __init__(self, message: str = "Token budget exceeded", **kwargs: object) -> None:
        super().__init__(error_code="token_budget_exceeded", message=message, **kwargs)


class BudgetSettlementExceededError(GatewayError):
    """Provider usage exceeded the capacity admitted before the provider call."""

    def __init__(
        self,
        message: str = "Provider usage exceeded budget reservation",
        **kwargs: object,
    ) -> None:
        super().__init__(
            error_code="budget_settlement_exceeded",
            message=message,
            retryable=False,
            error_layer=ErrorLayer.PROVIDER,
            **kwargs,
        )


class StreamFinalizationUnknownError(GatewayError):
    """The database may have committed; reconciliation must determine the outcome."""

    def __init__(
        self, message: str = "Stream finalization outcome is unknown", **kwargs: object
    ) -> None:
        super().__init__(
            error_code="stream_finalization_unknown",
            message=message,
            retryable=True,
            **kwargs,
        )


class ModelProfileNotFoundError(GatewayError):
    def __init__(self, profile_id: str, **kwargs: object) -> None:
        super().__init__(
            error_code="model_profile_not_found",
            message=f"Model profile '{profile_id}' not found",
            **kwargs,
        )


class ConfigError(GatewayError):
    def __init__(self, message: str = "Configuration error", **kwargs: object) -> None:
        super().__init__(error_code="config_error", message=message, **kwargs)


class GuardrailBlockedError(GatewayError):
    def __init__(
        self, message: str = "Request blocked by guardrail policy", **kwargs: object
    ) -> None:
        super().__init__(error_code="guardrail_blocked", message=message, retryable=False, **kwargs)


class StreamingNotSupportedError(GatewayError):
    def __init__(
        self, message: str = "Streaming is not enabled for this gateway", **kwargs: object
    ) -> None:
        super().__init__(
            error_code="streaming_not_supported", message=message, retryable=False, **kwargs
        )


class RequestNotFoundError(GatewayError):
    def __init__(self, request_id: str, **kwargs: object) -> None:
        super().__init__(
            error_code="request_not_found",
            message=f"Request '{request_id}' not found",
            retryable=False,
            **kwargs,
        )


class InternalError(GatewayError):
    """Unexpected, non-domain failure. Always mapped to HTTP 500.

    Raised by the orchestrator's last-resort handler so that even an unforeseen
    exception still produces a structured error AND an audit record.
    """

    def __init__(self, message: str = "Internal error", **kwargs: object) -> None:
        super().__init__(error_code="internal_error", message=message, retryable=False, **kwargs)


class RequestDeadlineExceededError(GatewayError):
    def __init__(
        self, message: str = "Overall request deadline exceeded", **kwargs: object
    ) -> None:
        super().__init__(error_code="request_timeout", message=message, retryable=False, **kwargs)


class ReplayUnavailableError(GatewayError):
    def __init__(self, message: str = "Replay data is unavailable", **kwargs: object) -> None:
        super().__init__(
            error_code="replay_unavailable", message=message, retryable=False, **kwargs
        )


# ── Provider-level errors ──


class ProviderTimeoutError(GatewayError):
    def __init__(self, provider_id: str, **kwargs: object) -> None:
        super().__init__(
            error_code="provider_timeout",
            message=f"Provider '{provider_id}' timed out",
            error_layer=ErrorLayer.PROVIDER,
            retryable=True,
            **kwargs,
        )


class ProviderFailedError(GatewayError):
    def __init__(self, provider_id: str, reason: str = "", **kwargs: object) -> None:
        super().__init__(
            error_code="provider_failed",
            message=f"Provider '{provider_id}' failed" + (f": {reason}" if reason else ""),
            error_layer=ErrorLayer.PROVIDER,
            retryable=True,
            **kwargs,
        )


class ProviderBadStatusError(GatewayError):
    def __init__(self, provider_id: str, status_code: int, **kwargs: object) -> None:
        super().__init__(
            error_code="provider_bad_status",
            message=f"Provider '{provider_id}' returned status {status_code}",
            error_layer=ErrorLayer.PROVIDER,
            retryable=True,
            **kwargs,
        )


class FallbackExhaustedError(GatewayError):
    def __init__(self, profile_id: str, **kwargs: object) -> None:
        super().__init__(
            error_code="fallback_exhausted",
            message=f"All providers exhausted for profile '{profile_id}'",
            error_layer=ErrorLayer.PROVIDER,
            retryable=False,
            **kwargs,
        )


# ── Error → HTTP status mapping (shared by the HTTP layer and the audit log) ──

ERROR_HTTP_STATUS: dict[str, int] = {
    "auth_failed": 401,
    "rate_limit_exceeded": 429,
    "rate_limit_backend_unavailable": 503,
    "token_budget_exceeded": 429,
    "budget_settlement_exceeded": 502,
    "stream_finalization_unknown": 503,
    "model_profile_not_found": 404,
    "config_error": 500,
    "internal_error": 500,
    "request_timeout": 504,
    "replay_unavailable": 409,
    "guardrail_blocked": 400,
    "streaming_not_supported": 400,
    "request_not_found": 404,
    "provider_timeout": 504,
    "provider_failed": 502,
    "provider_bad_status": 502,
    "fallback_exhausted": 502,
}


def http_status_for(error_code: str) -> int:
    return ERROR_HTTP_STATUS.get(error_code, 500)
