"""Disposable PostgreSQL migration, concurrency, and transaction evidence probe."""

from __future__ import annotations

import argparse
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.application.services.request_log_service import RequestLogService
from app.application.services.token_budget_service import TokenBudgetService
from app.domain.models.provider import ProviderAttempt
from app.infrastructure.config.config_models import ClientConfig, LoggingConfig, TokenBudgetConfig
from app.infrastructure.persistence.postgresql.connection import connect, migrate
from app.infrastructure.persistence.postgresql.repositories import (
    PostgresClientRepository,
    PostgresRequestLogRepository,
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
    PostgresClientRepository(database_url).sync([client])
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
    return {
        "migrations_twice": True,
        "budget_admitted": sum(admitted),
        "budget_rejected": 2 - sum(admitted),
        "budget_errors": reserve_errors,
        "committed_tokens": snapshot.used_tokens,
        "reserved_tokens": snapshot.reserved_tokens,
        "within_limit": snapshot.used_tokens + snapshot.reserved_tokens <= 100,
        "audit_failure_injected": rollback_observed,
        "request_rows_after_failure": request_rows,
        "attempt_rows_after_failure": attempt_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    result = run(args.database_url)
    print(result)
    passed = (
        result["budget_admitted"] == 1
        and result["within_limit"]
        and result["audit_failure_injected"]
        and result["request_rows_after_failure"] == 0
        and result["attempt_rows_after_failure"] == 0
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
