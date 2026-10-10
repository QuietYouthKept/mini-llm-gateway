from __future__ import annotations

import os

import pytest

from scripts.postgres_integration_probe import run

DATABASE_URL = os.getenv("GATEWAY_POSTGRES_URL") or os.getenv("WAVE3_POSTGRES_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL service is not configured")
def test_postgresql_reliability_probe_runs_inside_pytest_coverage() -> None:
    """Measure the real repository calls in the same process as pytest-cov."""
    assert DATABASE_URL is not None
    result = run(DATABASE_URL)

    assert result["budget_admitted"] == 1
    assert result["within_limit"] is True
    assert result["cold_budget_admitted"] == 1
    assert result["cold_budget_within_limit"] is True
    assert result["audit_failure_injected"] is True
    assert result["request_rows_after_failure"] == 0
    assert result["attempt_rows_after_failure"] == 0
    assert result["finalization_audit_failure_injected"] is True
    assert result["rollback_reservation_state"] == "reserved"
    assert result["rollback_finalization_rows"] == 0
    assert result["rollback_request_rows"] == 0
    assert result["commit_unknown_observed"] is True
    assert result["tcp_commit_ack_loss"]["oracle_pass"] is True
    assert (
        result["tcp_commit_ack_loss"]["client_observed_commit_error"]
        == "psycopg.OperationalError"
    )
    assert result["tcp_commit_ack_loss"]["reservation_state"] == "settled"
    assert result["tcp_commit_ack_loss"]["usage_tokens"] == 12
    assert result["tcp_commit_ack_loss"]["audit_count"] == 1
    assert result["tcp_commit_ack_loss"]["attempt_count"] == 1
    assert result["commit_unknown_receipt_recovered"] is True
    assert result["finalization_replay_idempotent"] is True
    assert result["finalization_request_rows"] == 1
    assert result["concurrent_finalization_replay_seen"] is True
    assert result["concurrent_finalization_request_rows"] == 1
    assert result["negative_usage_rejected"] is True
    assert result["orphan_reclaimed"] >= 1
    assert result["orphan_receipt"] == "release"
