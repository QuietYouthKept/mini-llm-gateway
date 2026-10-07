"""Token and cost budget enforcement backed by SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import BudgetSettlementExceededError, TokenBudgetExceededError
from app.domain.ports.repositories import BudgetRepositoryPort
from app.infrastructure.config.config_models import ClientConfig

_PERIOD_FORMATS = {
    "daily": "%Y-%m-%d",
    "monthly": "%Y-%m",
    "hourly": "%Y-%m-%d-%H",
}


@dataclass
class BudgetSnapshot:
    used_tokens: int
    used_cost_usd: float
    limit_tokens: int
    limit_cost_usd: float
    reserved_tokens: int = 0
    reserved_cost_usd: float = 0.0

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.limit_tokens - self.used_tokens - self.reserved_tokens)

    @property
    def remaining_cost_usd(self) -> float:
        if self.limit_cost_usd <= 0:
            return float("inf")
        return max(
            0.0,
            self.limit_cost_usd - self.used_cost_usd - self.reserved_cost_usd,
        )


class TokenBudgetService:
    def __init__(
        self, repository: BudgetRepositoryPort, *, reservation_lease_seconds: int = 30
    ) -> None:
        self._repo = repository
        self._reservation_lease_seconds = max(1, reservation_lease_seconds)

    def period_key(self, period: str) -> str:
        fmt = _PERIOD_FORMATS.get(period, "%Y-%m-%d")
        return datetime.now().strftime(fmt)

    def snapshot(self, client: ClientConfig) -> BudgetSnapshot:
        key = self.period_key(client.token_budget.period)
        usage = self._repo.get_usage(client.client_id, key)
        return BudgetSnapshot(
            used_tokens=int(usage["tokens_used"]),
            used_cost_usd=float(usage["cost_used_usd"]),
            limit_tokens=client.token_budget.max_tokens,
            limit_cost_usd=client.token_budget.max_cost_usd,
            reserved_tokens=int(usage.get("tokens_reserved", 0)),
            reserved_cost_usd=float(usage.get("cost_reserved_usd", 0.0)),
        )

    def ensure_capacity(
        self,
        client: ClientConfig,
        estimated_tokens: int,
        estimated_cost_usd: float = 0.0,
    ) -> BudgetSnapshot:
        """Raise TokenBudgetExceededError if the request cannot fit in budget."""
        snap = self.snapshot(client)
        if estimated_tokens > snap.remaining_tokens:
            raise TokenBudgetExceededError(
                message=(
                    f"Token budget exceeded for client '{client.client_id}': "
                    f"estimated {estimated_tokens} tokens, {snap.remaining_tokens} remaining"
                )
            )
        if client.token_budget.max_cost_usd > 0 and estimated_cost_usd > snap.remaining_cost_usd:
            raise TokenBudgetExceededError(
                message=f"Cost budget exceeded for client '{client.client_id}'"
            )
        return snap

    def reserve(
        self,
        reservation_id: str,
        client: ClientConfig,
        estimated_tokens: int,
        estimated_cost_usd: float = 0.0,
    ) -> BudgetSnapshot:
        """Atomically admit and reserve capacity at the database boundary."""
        key = self.period_key(client.token_budget.period)
        allowed = self._repo.try_reserve(
            reservation_id,
            client.client_id,
            key,
            estimated_tokens,
            estimated_cost_usd,
            client.token_budget.max_tokens,
            client.token_budget.max_cost_usd,
            self._reservation_lease_seconds,
        )
        if not allowed:
            raise TokenBudgetExceededError(
                message=(
                    f"Token/cost budget cannot reserve request for client '{client.client_id}'"
                )
            )
        return self.snapshot(client)

    def settle(
        self,
        reservation_id: str,
        client: ClientConfig,
        tokens: int,
        cost_usd: float,
    ) -> BudgetSnapshot:
        settled = self._repo.settle(reservation_id, tokens, cost_usd)
        if not settled:
            raise BudgetSettlementExceededError(
                message=(
                    f"Provider usage ({tokens} tokens, ${cost_usd:.8f}) exceeded "
                    f"reservation '{reservation_id}'"
                )
            )
        return self.snapshot(client)

    def release(self, reservation_id: str) -> bool:
        """Release once; a settled or already-released reservation is a no-op."""
        return self._repo.release(reservation_id)

    def reconcile_expired_reservations(self) -> int:
        """Explicit maintenance hook for reservations orphaned by process crashes."""
        return self._repo.reconcile_expired_reservations()

    def commit(
        self,
        client: ClientConfig,
        tokens: int,
        cost_usd: float,
    ) -> BudgetSnapshot:
        key = self.period_key(client.token_budget.period)
        self._repo.increment(client.client_id, key, tokens, cost_usd)
        return self.snapshot(client)
