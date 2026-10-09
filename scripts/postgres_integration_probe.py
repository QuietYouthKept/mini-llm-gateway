"""Disposable PostgreSQL migration, concurrency, and transaction evidence probe."""

from __future__ import annotations

import argparse
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.application.services.request_log_service import RequestLogService
from app.application.services.token_budget_service import TokenBudgetService
from app.domain.models.provider import ProviderAttempt
from app.domain.ports.repositories import FinalizeStreamCommand
from app.infrastructure.config.config_models import ClientConfig, LoggingConfig, TokenBudgetConfig
from app.infrastructure.persistence.postgresql.connection import connect, migrate
from app.infrastructure.persistence.postgresql.repositories import (
    PostgresClientRepository,
    PostgresRequestLogRepository,
    PostgresStreamingFinalizationRepository,
    PostgresTokenBudgetRepository,
)


def run(database_url: str) -> dict:
    migrate(database_url)
    migrate(database_url)
    suffix = uuid.uuid4().hex[:12]
    client = ClientConfig(
        client_id=f"pg-probe-{suffix}",
        api_key=f"pg-probe-key-{suffix}",
        token_budget=TokenBudgetConfig(period="daily", max_tokens=100),
    )
    final_client = ClientConfig(
        client_id=f"pg-final-{suffix}",
        api_key=f"pg-final-key-{suffix}",
        token_budget=TokenBudgetConfig(period="daily", max_tokens=100),
    )
    cold_client = ClientConfig(
        client_id=f"pg-cold-{suffix}",
        api_key=f"pg-cold-key-{suffix}",
        token_budget=TokenBudgetConfig(period="daily", max_tokens=100),
    )
    PostgresClientRepository(database_url).sync([client, final_client, cold_client])
    budget = TokenBudgetService(PostgresTokenBudgetRepository(database_url))
    budget.commit(client, 80, 0.0)

    reserve_errors: list[str] = []

    def reserve(index: int) -> bool:
        try:
            budget.reserve(f"pg-res-{suffix}-{index}", client, 15, 0.0)
            return True
        except Exception as exc:
            reserve_errors.append(f"{type(exc).__name__}: {exc}")
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = list(pool.map(reserve, (1, 2)))
    snapshot = budget.snapshot(client)

    # Exercise the missing usage-row case with concurrent reservations. The
    # SQL predicate must treat absent counters as zero, not NULL/unknown.
    cold_barrier = Barrier(2)

    def reserve_cold(index: int) -> bool:
        cold_barrier.wait()
        try:
            budget.reserve(f"pg-cold-res-{suffix}-{index}", cold_client, 60, 0.0)
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        cold_admitted = list(pool.map(reserve_cold, (1, 2)))
    cold_snapshot = budget.snapshot(cold_client)

    request_id = f"pg-audit-{suffix}"
    repository = PostgresRequestLogRepository(database_url)
    logger = RequestLogService(repository, LoggingConfig())
    with connect(database_url) as conn:
        from psycopg import sql

        conn.execute(
            sql.SQL("""CREATE OR REPLACE FUNCTION gateway_probe_fail_second_attempt()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
              IF NEW.request_id={} AND NEW.attempt_order=1 THEN
                RAISE EXCEPTION 'injected second attempt failure';
              END IF;
              RETURN NEW;
            END $$""").format(sql.Literal(request_id))
        )
        conn.execute(
            """CREATE TRIGGER gateway_probe_attempt_failure BEFORE INSERT ON provider_attempts
            FOR EACH ROW EXECUTE FUNCTION gateway_probe_fail_second_attempt()"""
        )
    rollback_observed = False
    try:
        logger.record_error(
            request_id=request_id,
            client_id=client.client_id,
            model_profile="probe",
            endpoint="/probe",
            status_code=502,
            error_code="injected",
            error_message="injected",
            duration_ms=1,
            attempts=[
                ProviderAttempt(provider_id="p1", attempt_order=0, status="error"),
                ProviderAttempt(provider_id="p2", attempt_order=1, status="error"),
            ],
        )
    except Exception:
        rollback_observed = True
    finally:
        with connect(database_url) as conn:
            conn.execute("DROP TRIGGER gateway_probe_attempt_failure ON provider_attempts")
            conn.execute("DROP FUNCTION gateway_probe_fail_second_attempt()")
    with connect(database_url) as conn:
        request_rows = conn.execute(
            "SELECT count(*) AS count FROM request_logs WHERE request_id=%s", (request_id,)
        ).fetchone()["count"]
        attempt_rows = conn.execute(
            "SELECT count(*) AS count FROM provider_attempts WHERE request_id=%s", (request_id,)
        ).fetchone()["count"]

    final_budget = TokenBudgetService(PostgresTokenBudgetRepository(database_url))
    final_reservation = f"pg-final-res-{suffix}"
    final_request = f"pg-final-request-{suffix}"
    final_budget.reserve(final_reservation, final_client, 30, 0.0)
    final_logger = RequestLogService(repository, LoggingConfig())
    final_row, final_attempts = final_logger.build_stream_record(
        request_id=final_request,
        client_id=final_client.client_id,
        model_profile="probe",
        endpoint="/probe",
        selected_provider="probe-provider",
        status="completed",
        status_code=200,
        usage={
            "billed_input": 6,
            "billed_output": 4,
            "actual_input": 6,
            "actual_output": 4,
            "source": "provider",
        },
        estimated_input=6,
        estimated_output=4,
        estimated_cost_usd=0.0,
        budget_before=100,
        duration_ms=1,
        attempts=[ProviderAttempt(provider_id="probe-provider", attempt_order=0, status="success")],
        decision_trace=[],
        replay_payload=None,
        response_content="probe",
    )
    finalizer = PostgresStreamingFinalizationRepository(database_url)
    command = FinalizeStreamCommand(
        reservation_id=final_reservation,
        request_id=final_request,
        operation="settle",
        tokens=10,
        cost_usd=0.0,
        payload_fingerprint=f"fingerprint-{suffix}",
        request_row=final_row,
        attempts=final_attempts,
    )
    with connect(database_url) as conn:
        from psycopg import sql

        conn.execute(
            sql.SQL("""CREATE OR REPLACE FUNCTION gateway_probe_fail_finalization_audit()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
              IF NEW.request_id={} THEN
                RAISE EXCEPTION 'injected finalization audit failure';
              END IF;
              RETURN NEW;
            END $$""").format(sql.Literal(final_request))
        )
        conn.execute(
            """CREATE TRIGGER gateway_probe_finalization_audit_failure
            BEFORE INSERT ON provider_attempts FOR EACH ROW
            EXECUTE FUNCTION gateway_probe_fail_finalization_audit()"""
        )
    finalization_rollback_observed = False
    try:
        finalizer.finalize_stream(command)
    except Exception:
        finalization_rollback_observed = True
    finally:
        with connect(database_url) as conn:
            conn.execute(
                "DROP TRIGGER gateway_probe_finalization_audit_failure ON provider_attempts"
            )
            conn.execute("DROP FUNCTION gateway_probe_fail_finalization_audit()")
    with connect(database_url) as conn:
        rollback_reservation_state = conn.execute(
            "SELECT state FROM token_budget_reservations WHERE reservation_id=%s",
            (final_reservation,),
        ).fetchone()["state"]
        rollback_finalization_rows = conn.execute(
            "SELECT count(*) AS count FROM stream_finalizations WHERE reservation_id=%s",
            (final_reservation,),
        ).fetchone()["count"]
        rollback_request_rows = conn.execute(
            "SELECT count(*) AS count FROM request_logs WHERE request_id=%s",
            (final_request,),
        ).fetchone()["count"]

    class LostCommitAcknowledgement:
        """Model a dropped client acknowledgement after the real DB commit."""

        def __init__(self) -> None:
            self.lost = False

        def finalize_stream(self, finalize_command):  # noqa: ANN001, ANN201
            receipt = finalizer.finalize_stream(finalize_command)
            if not self.lost:
                self.lost = True
                raise OSError("injected connection loss after PostgreSQL commit")
            return receipt

    unknown_result_observed = False
    try:
        LostCommitAcknowledgement().finalize_stream(command)
    except OSError:
        unknown_result_observed = True
    recovered_receipt = finalizer.get_finalization(final_reservation)
    replay_receipt = finalizer.finalize_stream(command)
    with connect(database_url) as conn:
        final_request_rows = conn.execute(
            "SELECT count(*) AS count FROM request_logs WHERE request_id=%s",
            (final_request,),
        ).fetchone()["count"]
        final_usage = conn.execute(
            "SELECT tokens_used FROM token_budget_usage WHERE client_id=%s",
            (final_client.client_id,),
        ).fetchone()["tokens_used"]

    concurrent_reservation = f"pg-concurrent-res-{suffix}"
    concurrent_request = f"pg-concurrent-request-{suffix}"
    final_budget.reserve(concurrent_reservation, final_client, 30, 0.0)
    concurrent_row, concurrent_attempts = final_logger.build_stream_record(
        request_id=concurrent_request,
        client_id=final_client.client_id,
        model_profile="probe",
        endpoint="/probe",
        selected_provider="probe-provider",
        status="completed",
        status_code=200,
        usage={
            "billed_input": 6,
            "billed_output": 4,
            "actual_input": 6,
            "actual_output": 4,
            "source": "provider",
        },
        estimated_input=6,
        estimated_output=4,
        estimated_cost_usd=0.0,
        budget_before=90,
        duration_ms=1,
        attempts=[],
        decision_trace=[],
        replay_payload=None,
        response_content="probe",
    )
    concurrent_command = FinalizeStreamCommand(
        reservation_id=concurrent_reservation,
        request_id=concurrent_request,
        operation="settle",
        tokens=10,
        cost_usd=0.0,
        payload_fingerprint=f"concurrent-fingerprint-{suffix}",
        request_row=concurrent_row,
        attempts=concurrent_attempts,
    )
    barrier = Barrier(2)

    def finalize_concurrently():  # noqa: ANN202
        barrier.wait()
        return PostgresStreamingFinalizationRepository(database_url).finalize_stream(
            concurrent_command
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent_receipts = list(pool.map(lambda _: finalize_concurrently(), range(2)))
    with connect(database_url) as conn:
        concurrent_request_rows = conn.execute(
            "SELECT count(*) AS count FROM request_logs WHERE request_id=%s",
            (concurrent_request,),
        ).fetchone()["count"]
    negative_usage_rejected = False
    try:
        with connect(database_url) as conn:
            conn.execute(
                "UPDATE token_budget_usage SET tokens_used=-1 WHERE client_id=%s",
                (final_client.client_id,),
            )
    except Exception:
        negative_usage_rejected = True

    orphan_request = f"pg-orphan-request-{suffix}"
    orphan_reservation = f"{orphan_request}:lease"
    final_budget.reserve(orphan_reservation, final_client, 5, 0.0)
    with connect(database_url) as conn:
        conn.execute(
            "UPDATE token_budget_reservations SET expires_at=now() - interval '1 second' "
            "WHERE reservation_id=%s",
            (orphan_reservation,),
        )
    orphan_reclaimed = final_budget.reconcile_expired_reservations()
    with connect(database_url) as conn:
        orphan_audit = conn.execute(
            "SELECT status,error_code FROM request_logs WHERE request_id=%s",
            (orphan_request,),
        ).fetchone()
        orphan_receipt = conn.execute(
            "SELECT operation FROM stream_finalizations WHERE reservation_id=%s",
            (orphan_reservation,),
        ).fetchone()
    return {
        "migrations_twice": True,
        "budget_admitted": sum(admitted),
        "budget_rejected": 2 - sum(admitted),
        "budget_errors": reserve_errors,
        "committed_tokens": snapshot.used_tokens,
        "reserved_tokens": snapshot.reserved_tokens,
        "within_limit": snapshot.used_tokens + snapshot.reserved_tokens <= 100,
        "cold_budget_admitted": sum(cold_admitted),
        "cold_budget_reserved": cold_snapshot.reserved_tokens,
        "cold_budget_within_limit": (
            cold_snapshot.used_tokens + cold_snapshot.reserved_tokens <= 100
        ),
        "audit_failure_injected": rollback_observed,
        "request_rows_after_failure": request_rows,
        "attempt_rows_after_failure": attempt_rows,
        "finalization_audit_failure_injected": finalization_rollback_observed,
        "rollback_reservation_state": rollback_reservation_state,
        "rollback_finalization_rows": rollback_finalization_rows,
        "rollback_request_rows": rollback_request_rows,
        "commit_unknown_observed": unknown_result_observed,
        "commit_unknown_receipt_recovered": recovered_receipt is not None,
        "finalization_state": recovered_receipt.state if recovered_receipt else None,
        "finalization_replay_idempotent": replay_receipt.already_applied,
        "finalization_tokens": replay_receipt.tokens,
        "finalization_request_rows": final_request_rows,
        "finalization_tokens_used": final_usage,
        "concurrent_finalization_states": [receipt.state for receipt in concurrent_receipts],
        "concurrent_finalization_replay_seen": any(
            receipt.already_applied for receipt in concurrent_receipts
        ),
        "concurrent_finalization_request_rows": concurrent_request_rows,
        "negative_usage_rejected": negative_usage_rejected,
        "orphan_reclaimed": orphan_reclaimed,
        "orphan_audit": dict(orphan_audit) if orphan_audit else None,
        "orphan_receipt": orphan_receipt["operation"] if orphan_receipt else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    result = run(args.database_url)
    print(json.dumps(result, indent=2, sort_keys=True))
    passed = (
        result["budget_admitted"] == 1
        and result["within_limit"]
        and result["cold_budget_admitted"] == 1
        and result["cold_budget_reserved"] == 60
        and result["cold_budget_within_limit"]
        and result["audit_failure_injected"]
        and result["request_rows_after_failure"] == 0
        and result["attempt_rows_after_failure"] == 0
        and result["finalization_audit_failure_injected"]
        and result["rollback_reservation_state"] == "reserved"
        and result["rollback_finalization_rows"] == 0
        and result["rollback_request_rows"] == 0
        and result["commit_unknown_observed"]
        and result["commit_unknown_receipt_recovered"]
        and result["finalization_state"] == "settled"
        and result["finalization_replay_idempotent"]
        and result["finalization_tokens"] == 10
        and result["finalization_request_rows"] == 1
        and result["finalization_tokens_used"] == 10
        and result["concurrent_finalization_states"] == ["settled", "settled"]
        and result["concurrent_finalization_replay_seen"]
        and result["concurrent_finalization_request_rows"] == 1
        and result["negative_usage_rejected"]
        and result["orphan_reclaimed"] >= 1
        and result["orphan_audit"]
        == {"status": "orphaned_released", "error_code": "reservation_lease_expired"}
        and result["orphan_receipt"] == "release"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
