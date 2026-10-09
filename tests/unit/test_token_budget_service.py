"""Tests for the SQLite-backed token budget service."""

from __future__ import annotations

import sqlite3

import pytest

from app.application.services.token_budget_service import TokenBudgetService
from app.domain.errors import BudgetSettlementExceededError, TokenBudgetExceededError
from app.domain.ports.repositories import FinalizationConflictError, FinalizeStreamCommand
from app.infrastructure.config.config_models import ClientConfig, TokenBudgetConfig
from app.infrastructure.persistence.sqlite.connection import get_connection, init_db
from app.infrastructure.persistence.sqlite.repositories import (
    ClientRepository,
    RequestLogRepository,
    SQLiteStreamingFinalizationRepository,
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
    with get_connection(db) as conn:
        audit = conn.execute(
            "SELECT status, error_code FROM request_logs WHERE request_id='expired'"
        ).fetchone()
        receipt = conn.execute(
            "SELECT operation FROM stream_finalizations WHERE reservation_id='expired'"
        ).fetchone()
    assert dict(audit) == {
        "status": "orphaned_released",
        "error_code": "reservation_lease_expired",
    }
    assert receipt["operation"] == "release"


def test_expired_reservation_cannot_settle_before_maintenance_runs(tmp_path) -> None:
    db = str(tmp_path / "expired-settlement.db")
    init_db(db)
    client = make_client(100)
    ClientRepository(db).sync([client])
    service = TokenBudgetService(TokenBudgetRepository(db), reservation_lease_seconds=1)
    service.reserve("expired", client, 40)
    with get_connection(db) as conn:
        conn.execute(
            "UPDATE token_budget_reservations SET expires_at = datetime('now', '-1 second') "
            "WHERE reservation_id = 'expired'"
        )
        conn.commit()
    with pytest.raises(BudgetSettlementExceededError):
        service.settle("expired", client, 20, 0.0)
    assert service.snapshot(client).used_tokens == 0
    assert service.snapshot(client).reserved_tokens == 0


def _terminal_row(request_id: str) -> dict:
    return {
        "request_id": request_id,
        "client_id": "c1",
        "model_profile": "p",
        "endpoint": "/v1/chat",
        "selected_provider": "mock",
        "fallback_used": 0,
        "status": "completed",
        "status_code": 200,
        "input_tokens": 1,
        "output_tokens": 1,
        "estimated_input_tokens": 1,
        "estimated_output_tokens": 1,
        "actual_input_tokens": None,
        "actual_output_tokens": None,
        "usage_source": "estimated",
        "estimated_tokens": 2,
        "estimated_cost_usd": 0.0,
        "cost_saved_usd": 0.0,
        "budget_before": 100,
        "budget_after": None,
        "duration_ms": 1,
        "error_code": None,
        "error_message": None,
        "cache_hit": 0,
        "cache_key": None,
        "decision_trace": None,
        "replay_payload": None,
        "request_body": None,
        "response_body": None,
    }


def test_stream_finalization_is_atomic_and_idempotent(tmp_path) -> None:
    db = str(tmp_path / "finalize.db")
    init_db(db)
    ClientRepository(db).sync([make_client(100)])
    budget = TokenBudgetService(TokenBudgetRepository(db))
    budget.reserve("r1", make_client(100), 20)
    repo = SQLiteStreamingFinalizationRepository(db)
    command = FinalizeStreamCommand("r1", "q1", "settle", 10, 0.0, "same", _terminal_row("q1"), [])
    first = repo.finalize_stream(command)
    second = repo.finalize_stream(command)
    assert first.state == "settled" and second.already_applied
    assert budget.snapshot(make_client(100)).used_tokens == 10
    with pytest.raises(FinalizationConflictError):
        repo.finalize_stream(
            FinalizeStreamCommand(
                "r1", "q1", "settle", 11, 0.0, "different", _terminal_row("q1"), []
            )
        )


def test_stream_finalization_rolls_back_budget_when_audit_insert_fails(tmp_path) -> None:
    db = str(tmp_path / "finalize-rollback.db")
    init_db(db)
    client = make_client(100)
    ClientRepository(db).sync([client])
    budget = TokenBudgetService(TokenBudgetRepository(db))
    budget.reserve("r1", client, 20)
    RequestLogRepository(db).insert_request_with_attempts(_terminal_row("duplicate"), [])

    repo = SQLiteStreamingFinalizationRepository(db)
    command = FinalizeStreamCommand(
        "r1", "duplicate", "settle", 10, 0.0, "payload", _terminal_row("duplicate"), []
    )
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        repo.finalize_stream(command)

    with get_connection(db) as conn:
        reservation = conn.execute(
            "SELECT state FROM token_budget_reservations WHERE reservation_id='r1'"
        ).fetchone()
        finalizations = conn.execute("SELECT count(*) FROM stream_finalizations").fetchone()[0]
    assert reservation["state"] == "reserved"
    assert finalizations == 0
    assert budget.snapshot(client).used_tokens == 0
    assert budget.snapshot(client).reserved_tokens == 20


def test_sqlite_rejects_negative_budget_storage_values(tmp_path) -> None:
    db = str(tmp_path / "nonnegative.db")
    init_db(db)
    ClientRepository(db).sync([make_client(100)])
    with get_connection(db) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="non-negative"):
            conn.execute(
                "INSERT INTO token_budget_usage(client_id, period, tokens_used, cost_used_usd) "
                "VALUES ('c1', 'daily', -1, 0)"
            )
        with pytest.raises(sqlite3.IntegrityError, match="non-negative"):
            conn.execute(
                "INSERT INTO token_budget_reservations "
                "(reservation_id, client_id, period, tokens_reserved, "
                "cost_reserved_usd, expires_at) "
                "VALUES ('negative', 'c1', 'daily', -1, 0, datetime('now', '+1 minute'))"
            )
