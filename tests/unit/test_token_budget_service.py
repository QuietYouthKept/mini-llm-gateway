"""Tests for the SQLite-backed token budget service."""

from __future__ import annotations

import pytest

from app.application.services.token_budget_service import TokenBudgetService
from app.domain.errors import BudgetSettlementExceededError, TokenBudgetExceededError
from app.infrastructure.config.config_models import ClientConfig, TokenBudgetConfig
from app.infrastructure.persistence.sqlite.connection import get_connection, init_db
from app.infrastructure.persistence.sqlite.repositories import (
    ClientRepository,
    TokenBudgetRepository,
)


def make_client(max_tokens: int = 100) -> ClientConfig:
    return ClientConfig(
        client_id="c1",
        api_key="k",
        token_budget=TokenBudgetConfig(period="daily", max_tokens=max_tokens),
    )


@pytest.fixture
def service(tmp_path) -> TokenBudgetService:
    db = str(tmp_path / "budget.db")
    init_db(db)
    ClientRepository(db).sync([make_client(100)])
    return TokenBudgetService(TokenBudgetRepository(db))


def test_initial_snapshot_is_full(service: TokenBudgetService) -> None:
    snap = service.snapshot(make_client(100))
    assert snap.used_tokens == 0
    assert snap.remaining_tokens == 100


def test_commit_increases_usage(service: TokenBudgetService) -> None:
    client = make_client(100)
    service.commit(client, 30, 0.0)
    snap = service.snapshot(client)
    assert snap.used_tokens == 30
    assert snap.remaining_tokens == 70


def test_ensure_capacity_allows_within_budget(service: TokenBudgetService) -> None:
    client = make_client(100)
    snap = service.ensure_capacity(client, 50)
    assert snap.remaining_tokens == 100


def test_ensure_capacity_raises_when_over(service: TokenBudgetService) -> None:
    client = make_client(100)
    service.commit(client, 90, 0.0)
    with pytest.raises(TokenBudgetExceededError):
        service.ensure_capacity(client, 20)


def test_settle_releases_unused_reservation(service: TokenBudgetService) -> None:
    client = make_client(100)
    service.reserve("under", client, 100, 0.0)
    settled = service.settle("under", client, 60, 0.0)
    assert settled.used_tokens == 60
    assert settled.reserved_tokens == 0
    assert settled.remaining_tokens == 40


def test_settle_refuses_provider_usage_above_reservation(service: TokenBudgetService) -> None:
    client = make_client(100)
    service.reserve("over", client, 60, 0.0)
    with pytest.raises(BudgetSettlementExceededError):
        service.settle("over", client, 80, 0.0)
    held = service.snapshot(client)
    assert held.used_tokens == 0
    assert held.reserved_tokens == 60
    service.release("over")
    assert service.snapshot(client).reserved_tokens == 0


def test_settle_is_single_use_and_release_is_idempotent(service: TokenBudgetService) -> None:
    client = make_client(100)
    service.reserve("once", client, 30, 0.0)
    service.settle("once", client, 20, 0.0)
    with pytest.raises(ValueError, match="state 'settled'"):
        service.settle("once", client, 20, 0.0)
    service.release("once")
    service.release("once")
    assert service.snapshot(client).used_tokens == 20


def test_settlement_state_machine_rejects_invalid_transitions(
    service: TokenBudgetService,
) -> None:
    client = make_client(100)
    service.reserve("settled", client, 30)
    service.settle("settled", client, 20, 0.0)
    with pytest.raises(ValueError, match="state 'settled'"):
        service.settle("settled", client, 20, 0.0)
    assert service.release("settled") is False

    service.reserve("released", client, 30)
    assert service.release("released") is True
    assert service.release("released") is False
    with pytest.raises(ValueError, match="state 'released'"):
        service.settle("released", client, 20, 0.0)
    assert service.snapshot(client).used_tokens == 20
    assert service.snapshot(client).reserved_tokens == 0


def test_reconcile_reclaims_only_expired_reserved_rows(tmp_path) -> None:
    db = str(tmp_path / "lease.db")
    init_db(db)
    client = make_client(100)
    ClientRepository(db).sync([client])
    service = TokenBudgetService(TokenBudgetRepository(db), reservation_lease_seconds=60)
    service.reserve("expired", client, 40)
    service.reserve("active", client, 30)
    service.settle("active", client, 20, 0.0)
    with get_connection(db) as conn:
        conn.execute(
            "UPDATE token_budget_reservations SET expires_at = datetime('now', '-1 second') "
            "WHERE reservation_id = 'expired'"
        )
        conn.commit()
    assert service.reconcile_expired_reservations() == 1
    assert service.reconcile_expired_reservations() == 0
    assert service.snapshot(client).reserved_tokens == 0
    assert service.snapshot(client).used_tokens == 20
