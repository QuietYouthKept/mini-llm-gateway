"""PostgreSQL repositories implementing the Gateway persistence ports."""

from __future__ import annotations

import json
from typing import Any

from app.domain.ports.repositories import (
    FinalizationConflictError,
    FinalizationReceipt,
    FinalizationRejectedError,
    FinalizeStreamCommand,
)
from app.infrastructure.config.config_models import ClientConfig
from app.infrastructure.persistence.postgresql.connection import connect


def _json_value(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


class PostgresClientRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def sync(self, clients: list[ClientConfig]) -> None:
        with connect(self._database_url) as conn:
            for client in clients:
                conn.execute(
                    """INSERT INTO clients (
                    client_id, api_key, enabled, rate_limit_requests_per_minute,
                    budget_period, budget_max_tokens, budget_max_cost_usd
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (client_id) DO UPDATE SET
                    api_key=excluded.api_key, enabled=excluded.enabled,
                    rate_limit_requests_per_minute=excluded.rate_limit_requests_per_minute,
                    budget_period=excluded.budget_period,
                    budget_max_tokens=excluded.budget_max_tokens,
                    budget_max_cost_usd=excluded.budget_max_cost_usd,
                    updated_at=now()""",
                    (
                        client.client_id,
                        client.api_key,
                        client.enabled,
                        client.rate_limit.requests_per_minute,
                        client.token_budget.period,
                        client.token_budget.max_tokens,
                        client.token_budget.max_cost_usd,
                    ),
                )


class PostgresTokenBudgetRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def get_usage(self, client_id: str, period: str) -> dict[str, float]:
        with connect(self._database_url) as conn:
            row = conn.execute(
                """SELECT
                COALESCE((SELECT tokens_used FROM token_budget_usage
                  WHERE client_id=%s AND period=%s), 0) AS tokens_used,
                COALESCE((SELECT cost_used_usd FROM token_budget_usage
                  WHERE client_id=%s AND period=%s), 0) AS cost_used_usd,
                COALESCE((SELECT sum(tokens_reserved) FROM token_budget_reservations
                  WHERE client_id=%s AND period=%s AND state='reserved'), 0) AS tokens_reserved,
                COALESCE((SELECT sum(cost_reserved_usd) FROM token_budget_reservations
                  WHERE client_id=%s AND period=%s AND state='reserved'), 0)
                  AS cost_reserved_usd""",
                (client_id, period, client_id, period, client_id, period, client_id, period),
            ).fetchone()
            return {key: float(value) for key, value in row.items()}

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
    ) -> bool:
        with connect(self._database_url) as conn:
            row = conn.execute(
                """SELECT try_reserve_token_budget(
                %s::text,%s::text,%s::text,%s::bigint,%s::numeric,%s::bigint,%s::numeric,%s::integer
                ) AS allowed""",
                (
                    reservation_id,
                    client_id,
                    period,
                    tokens,
                    cost_usd,
                    limit_tokens,
                    limit_cost_usd,
                    lease_seconds,
                ),
            ).fetchone()
            return bool(row["allowed"])

    def settle(self, reservation_id: str, tokens: int, cost_usd: float) -> bool:
        with connect(self._database_url) as conn:
            reservation = conn.execute(
                """SELECT client_id, period, tokens_reserved, cost_reserved_usd, state,
                expires_at <= now() AS expired
                FROM token_budget_reservations WHERE reservation_id=%s FOR UPDATE""",
                (reservation_id,),
            ).fetchone()
            if reservation is None:
                raise ValueError(f"Unknown budget reservation '{reservation_id}'")
            if reservation["state"] != "reserved":
                raise ValueError(
                    f"Cannot settle reservation '{reservation_id}' in state "
                    f"'{reservation['state']}'"
                )
            if reservation["expired"]:
                conn.execute(
                    "UPDATE token_budget_reservations SET state='released', released_at=now() "
                    "WHERE reservation_id=%s AND state='reserved'",
                    (reservation_id,),
                )
                return False
            if (
                tokens > reservation["tokens_reserved"]
                or cost_usd > float(reservation["cost_reserved_usd"]) + 1e-12
            ):
                conn.rollback()
                return False
            conn.execute(
                """INSERT INTO token_budget_usage
                (client_id, period, tokens_used, cost_used_usd, last_updated)
                VALUES (%s,%s,%s,%s,now())
                ON CONFLICT (client_id,period) DO UPDATE SET
                tokens_used=token_budget_usage.tokens_used+excluded.tokens_used,
                cost_used_usd=token_budget_usage.cost_used_usd+excluded.cost_used_usd,
                last_updated=now()""",
                (reservation["client_id"], reservation["period"], tokens, cost_usd),
            )
            conn.execute(
                "UPDATE token_budget_reservations SET state='settled', settled_at=now() "
                "WHERE reservation_id=%s AND state='reserved'",
                (reservation_id,),
            )
            return True

    def release(self, reservation_id: str) -> bool:
        with connect(self._database_url) as conn:
            result = conn.execute(
                "UPDATE token_budget_reservations SET state='released', released_at=now() "
                "WHERE reservation_id=%s AND state='reserved'",
                (reservation_id,),
            )
            return result.rowcount == 1

    def reconcile_expired_reservations(self) -> int:
        with connect(self._database_url) as conn:
            expired = conn.execute(
                """SELECT reservation_id,client_id FROM token_budget_reservations
                WHERE state='reserved' AND expires_at <= now() FOR UPDATE"""
            ).fetchall()
            for reservation in expired:
                reservation_id = reservation["reservation_id"]
                request_id = reservation_id.split(":", 1)[0]
                PostgresRequestLogRepository._insert_with_connection(
                    conn,
                    self._orphaned_release_row(request_id, reservation["client_id"]),
                    [],
                )
                result = conn.execute(
                    "UPDATE token_budget_reservations SET state='released', released_at=now() "
                    "WHERE reservation_id=%s AND state='reserved'",
                    (reservation_id,),
                )
                if result.rowcount != 1:
                    raise FinalizationConflictError(
                        f"reservation '{reservation_id}' changed during reconciliation"
                    )
                conn.execute(
                    """INSERT INTO stream_finalizations
                    (reservation_id,request_id,operation,payload_fingerprint,tokens,cost_usd)
                    VALUES (%s,%s,'release','lease-expiry-release-v1',0,0)""",
                    (reservation_id, request_id),
                )
            return len(expired)

    @staticmethod
    def _orphaned_release_row(request_id: str, client_id: str) -> dict[str, Any]:
        return {
            "request_id": request_id,
            "client_id": client_id,
            "model_profile": None,
            "endpoint": None,
            "selected_provider": None,
            "fallback_used": 0,
            "status": "orphaned_released",
            "status_code": 503,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "actual_input_tokens": None,
            "actual_output_tokens": None,
            "usage_source": "not_billed",
            "estimated_tokens": 0,
            "estimated_cost_usd": 0.0,
            "cost_saved_usd": 0.0,
            "budget_before": None,
            "budget_after": None,
            "duration_ms": None,
            "error_code": "reservation_lease_expired",
            "error_message": "Reservation lease expired before stream finalization",
            "cache_hit": 0,
            "cache_key": None,
            "decision_trace": json.dumps(
                [{"step": "reconciled", "reason": "reservation_lease_expired"}]
            ),
            "replay_payload": None,
            "request_body": None,
            "response_body": None,
        }

    def increment(self, client_id: str, period: str, tokens: int, cost_usd: float) -> None:
        with connect(self._database_url) as conn:
            conn.execute(
                """INSERT INTO token_budget_usage
                (client_id,period,tokens_used,cost_used_usd,last_updated)
                VALUES (%s,%s,%s,%s,now()) ON CONFLICT (client_id,period) DO UPDATE SET
                tokens_used=token_budget_usage.tokens_used+excluded.tokens_used,
                cost_used_usd=token_budget_usage.cost_used_usd+excluded.cost_used_usd,
                last_updated=now()""",
                (client_id, period, tokens, cost_usd),
            )


class PostgresRequestLogRepository:
    _REQUEST_COLUMNS = (
        "request_id",
        "client_id",
        "model_profile",
        "endpoint",
        "selected_provider",
        "fallback_used",
        "status",
        "status_code",
        "input_tokens",
        "output_tokens",
        "estimated_input_tokens",
        "estimated_output_tokens",
        "actual_input_tokens",
        "actual_output_tokens",
        "usage_source",
        "estimated_tokens",
        "estimated_cost_usd",
        "cost_saved_usd",
        "budget_before",
        "budget_after",
        "duration_ms",
        "error_code",
        "error_message",
        "cache_hit",
        "cache_key",
        "decision_trace",
        "replay_payload",
        "request_body",
        "response_body",
    )

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def insert_request_with_attempts(
        self, row: dict[str, Any], attempts: list[dict[str, Any]]
    ) -> None:
        with connect(self._database_url) as conn:
            self._insert_with_connection(conn, row, attempts)

    @classmethod
    def _insert_with_connection(
        cls, conn: Any, row: dict[str, Any], attempts: list[dict[str, Any]]
    ) -> None:
        columns = ",".join(cls._REQUEST_COLUMNS)
        placeholders = ",".join(["%s"] * len(cls._REQUEST_COLUMNS))
        values = [row[column] for column in cls._REQUEST_COLUMNS]
        values[5] = bool(values[5])
        values[23] = bool(values[23])
        for index in (25, 26, 27, 28):
            values[index] = _json_value(values[index])
        try:
            from psycopg.types.json import Jsonb
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PostgreSQL backend requires psycopg[binary]") from exc
        for index in (25, 26, 27, 28):
            if values[index] is not None:
                values[index] = Jsonb(values[index])
        conn.execute(f"INSERT INTO request_logs ({columns}) VALUES ({placeholders})", values)
        for attempt in attempts:
            conn.execute(
                """INSERT INTO provider_attempts
                (request_id,provider_id,attempt_order,retry_index,status,status_code,
                 latency_ms,error_code,error_message,provider_request_id)
                VALUES (%(request_id)s,%(provider_id)s,%(attempt_order)s,%(retry_index)s,
                %(status)s,%(status_code)s,%(latency_ms)s,%(error_code)s,%(error_message)s,%(provider_request_id)s)""",
                attempt,
            )

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        with connect(self._database_url) as conn:
            row = conn.execute(
                "SELECT * FROM request_logs WHERE request_id=%s", (request_id,)
            ).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["attempts"] = list(
                conn.execute(
                    """SELECT provider_id,attempt_order,retry_index,status,status_code,
                    latency_ms,error_code,error_message,provider_request_id,created_at
                    FROM provider_attempts
                    WHERE request_id=%s ORDER BY attempt_order,retry_index""",
                    (request_id,),
                ).fetchall()
            )
            for key in ("created_at",):
                if result.get(key) is not None:
                    result[key] = result[key].isoformat()
            for attempt in result["attempts"]:
                if attempt.get("created_at") is not None:
                    attempt["created_at"] = attempt["created_at"].isoformat()
            return result


class PostgresStreamingFinalizationRepository:
    """PostgreSQL parity for atomic, idempotent streaming finalization."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def get_finalization(self, reservation_id: str) -> FinalizationReceipt | None:
        with connect(self._database_url) as conn:
            row = conn.execute(
                """SELECT f.reservation_id,f.request_id,f.operation,f.payload_fingerprint,
                r.state,f.tokens,f.cost_usd,
                f.budget_after FROM stream_finalizations f JOIN token_budget_reservations r
                ON r.reservation_id=f.reservation_id WHERE f.reservation_id=%s""",
                (reservation_id,),
            ).fetchone()
            if row is None:
                return None
            return FinalizationReceipt(
                row["reservation_id"],
                row["request_id"],
                row["operation"],
                row["payload_fingerprint"],
                row["state"],
                int(row["tokens"]),
                float(row["cost_usd"]),
                row["budget_after"],
                True,
            )

    def finalize_stream(self, command: FinalizeStreamCommand) -> FinalizationReceipt:
        if command.tokens < 0 or command.cost_usd < 0:
            raise FinalizationRejectedError("stream finalization usage must be non-negative")
        with connect(self._database_url) as conn:
            # Serialize duplicates on the reservation, which exists before a
            # finalization receipt.  Locking only a missing receipt leaves a
            # race where a concurrent replay sees no row, waits, then mistakes
            # the just-settled reservation for a conflict.
            reservation = conn.execute(
                """SELECT client_id,period,tokens_reserved,cost_reserved_usd,state,
                expires_at <= now() AS expired FROM token_budget_reservations
                WHERE reservation_id=%s FOR UPDATE""",
                (command.reservation_id,),
            ).fetchone()
            if reservation is None:
                raise FinalizationConflictError("unknown budget reservation")
            existing = conn.execute(
                """SELECT request_id,operation,payload_fingerprint,tokens,cost_usd,budget_after
                FROM stream_finalizations WHERE reservation_id=%s""",
                (command.reservation_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["request_id"] != command.request_id
                    or existing["payload_fingerprint"] != command.payload_fingerprint
                ):
                    raise FinalizationConflictError(
                        "finalization key was reused with different payload"
                    )
                state = conn.execute(
                    "SELECT state FROM token_budget_reservations WHERE reservation_id=%s",
                    (command.reservation_id,),
                ).fetchone()["state"]
                return FinalizationReceipt(
                    command.reservation_id,
                    command.request_id,
                    existing["operation"],
                    existing["payload_fingerprint"],
                    state,
                    int(existing["tokens"]),
                    float(existing["cost_usd"]),
                    existing["budget_after"],
                    True,
                )
            if reservation["state"] != "reserved":
                raise FinalizationConflictError(
                    "reservation has no finalization receipt and is not reserved"
                )
            if command.operation == "settle":
                if (
                    reservation["expired"]
                    or command.tokens > reservation["tokens_reserved"]
                    or command.cost_usd > float(reservation["cost_reserved_usd"]) + 1e-12
                ):
                    raise FinalizationRejectedError("stream settlement deterministically rejected")
                conn.execute(
                    """INSERT INTO token_budget_usage
                    (client_id,period,tokens_used,cost_used_usd,last_updated)
                    VALUES (%s,%s,%s,%s,now()) ON CONFLICT (client_id,period) DO UPDATE SET
                    tokens_used=token_budget_usage.tokens_used+excluded.tokens_used,
                    cost_used_usd=token_budget_usage.cost_used_usd+excluded.cost_used_usd,
                    last_updated=now()""",
                    (
                        reservation["client_id"],
                        reservation["period"],
                        command.tokens,
                        command.cost_usd,
                    ),
                )
                state = "settled"
                conn.execute(
                    "UPDATE token_budget_reservations SET state='settled',settled_at=now() "
                    "WHERE reservation_id=%s AND state='reserved'",
                    (command.reservation_id,),
                )
            else:
                if command.tokens != 0 or command.cost_usd != 0:
                    raise FinalizationRejectedError(
                        "release finalization must not carry billable usage"
                    )
                state = "released"
                conn.execute(
                    "UPDATE token_budget_reservations SET state='released',released_at=now() "
                    "WHERE reservation_id=%s AND state='reserved'",
                    (command.reservation_id,),
                )
            totals = conn.execute(
                """SELECT c.budget_max_tokens,
                COALESCE(u.tokens_used,0) AS used,
                COALESCE((SELECT sum(tokens_reserved) FROM token_budget_reservations r
                WHERE r.client_id=%s AND r.period=%s AND r.state='reserved'),0) AS reserved
                FROM clients c LEFT JOIN token_budget_usage u
                ON u.client_id=c.client_id AND u.period=%s WHERE c.client_id=%s""",
                (
                    reservation["client_id"],
                    reservation["period"],
                    reservation["period"],
                    reservation["client_id"],
                ),
            ).fetchone()
            budget_after = max(
                0, int(totals["budget_max_tokens"]) - int(totals["used"]) - int(totals["reserved"])
            )
            row = dict(command.request_row)
            row["budget_after"] = budget_after
            PostgresRequestLogRepository._insert_with_connection(conn, row, command.attempts)
            conn.execute(
                """INSERT INTO stream_finalizations
                (reservation_id,request_id,operation,payload_fingerprint,tokens,cost_usd,budget_after)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    command.reservation_id,
                    command.request_id,
                    command.operation,
                    command.payload_fingerprint,
                    command.tokens,
                    command.cost_usd,
                    budget_after,
                ),
            )
            return FinalizationReceipt(
                command.reservation_id,
                command.request_id,
                command.operation,
                command.payload_fingerprint,
                state,
                command.tokens,
                command.cost_usd,
                budget_after,
                False,
            )


class PostgresConfigEventRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def record(self, event_type: str, detail: str, checksum: str = "") -> None:
        with connect(self._database_url) as conn:
            conn.execute(
                "INSERT INTO config_events (event_type,detail,checksum) VALUES (%s,%s,%s)",
                (event_type, detail, checksum),
            )
