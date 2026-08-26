"""Repository and state-store ports used by application services."""

from __future__ import annotations

from typing import Any, Protocol


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
