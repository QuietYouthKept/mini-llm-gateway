"""Repository and state-store ports used by application services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class FinalizeStreamCommand:
    """One idempotent terminal stream decision, bound to its audit payload."""

    reservation_id: str
    request_id: str
    operation: Literal["settle", "release"]
    tokens: int
    cost_usd: float
    payload_fingerprint: str
    request_row: dict[str, Any]
    attempts: list[dict[str, Any]]


@dataclass(frozen=True)
class FinalizationReceipt:
    reservation_id: str
    request_id: str
    operation: Literal["settle", "release"]
    payload_fingerprint: str
    state: Literal["settled", "released"]
    tokens: int
    cost_usd: float
    budget_after: int | None
    already_applied: bool


class FinalizationConflictError(ValueError):
    """A reused idempotency key carries a different terminal payload."""


class FinalizationRejectedError(ValueError):
    """The database definitely rejected the requested terminal transition."""


class StreamingFinalizationRepositoryPort(Protocol):
    def finalize_stream(self, command: FinalizeStreamCommand) -> FinalizationReceipt: ...

    def get_finalization(self, reservation_id: str) -> FinalizationReceipt | None: ...


class BudgetRepositoryPort(Protocol):
    def get_usage(self, client_id: str, period: str) -> dict[str, float]: ...

    def try_reserve(
        self,
        reservation_id: str,
        client_id: str,
        period: str,
        tokens: int,
        cost_usd: float,
        limit_tokens: int,
        limit_cost_usd: float,
        lease_seconds: int,
    ) -> bool: ...

    def settle(self, reservation_id: str, tokens: int, cost_usd: float) -> bool: ...

    def release(self, reservation_id: str) -> bool: ...

    def reconcile_expired_reservations(self) -> int: ...

    def increment(self, client_id: str, period: str, tokens: int, cost_usd: float) -> None: ...


class RequestLogRepositoryPort(Protocol):
    def insert_request_with_attempts(
        self, row: dict[str, Any], attempts: list[dict[str, Any]]
    ) -> None: ...

    def get_request(self, request_id: str) -> dict[str, Any] | None: ...


class RateLimiterPort(Protocol):
    def check(self, key: str, limit: int) -> Any: ...


class PromptCachePort(Protocol):
    def get(self, key: str) -> Any: ...

    def put(self, key: str, response: Any) -> None: ...
