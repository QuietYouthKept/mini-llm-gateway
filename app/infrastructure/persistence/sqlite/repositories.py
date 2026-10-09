"""SQLite repositories for budget usage, request logs, and config events.

Each method opens its own connection, so the repositories are safe to call from
async handlers without shared mutable connection state. For a production
deployment these would be swapped for Postgres; the interfaces stay the same.
"""

# SQL statements intentionally remain readable as contiguous query fragments.
# ruff: noqa: E501

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

from app.domain.ports.repositories import (
    FinalizationConflictError,
    FinalizationReceipt,
    FinalizationRejectedError,
    FinalizeStreamCommand,
)
from app.infrastructure.config.config_models import ClientConfig
from app.infrastructure.persistence.sqlite.connection import get_connection


class ClientRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def sync(self, clients: list[ClientConfig]) -> None:
        """Upsert configured clients into the control-plane table."""
        conn = get_connection(self._db_path)
        try:
            for c in clients:
                conn.execute(
                    "INSERT INTO clients ("
                    "client_id, api_key, enabled, rate_limit_requests_per_minute, "
                    "budget_period, budget_max_tokens, budget_max_cost_usd"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(client_id) DO UPDATE SET "
                    "api_key = excluded.api_key, enabled = excluded.enabled, "
                    "rate_limit_requests_per_minute = excluded.rate_limit_requests_per_minute, "
                    "budget_period = excluded.budget_period, "
                    "budget_max_tokens = excluded.budget_max_tokens, "
                    "budget_max_cost_usd = excluded.budget_max_cost_usd, "
                    "updated_at = datetime('now')",
                    (
                        c.client_id,
                        c.api_key,
                        1 if c.enabled else 0,
                        c.rate_limit.requests_per_minute,
                        c.token_budget.period,
                        c.token_budget.max_tokens,
                        c.token_budget.max_cost_usd,
                    ),
                )
            conn.commit()
        finally:
            conn.close()


class TokenBudgetRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def get_usage(self, client_id: str, period: str) -> dict[str, float]:
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT COALESCE(u.tokens_used, 0) AS tokens_used, "
                "COALESCE(u.cost_used_usd, 0) AS cost_used_usd, "
                "COALESCE(SUM(r.tokens_reserved), 0) AS tokens_reserved, "
                "COALESCE(SUM(r.cost_reserved_usd), 0) AS cost_reserved_usd "
                "FROM (SELECT ? AS client_id, ? AS period) k "
                "LEFT JOIN token_budget_usage u "
                "ON u.client_id = k.client_id AND u.period = k.period "
                "LEFT JOIN token_budget_reservations r "
                "ON r.client_id = k.client_id AND r.period = k.period AND r.state = 'reserved'",
                (client_id, period),
            ).fetchone()
            return {
                "tokens_used": int(row["tokens_used"]),
                "cost_used_usd": float(row["cost_used_usd"]),
                "tokens_reserved": int(row["tokens_reserved"]),
                "cost_reserved_usd": float(row["cost_reserved_usd"]),
            }
        finally:
            conn.close()

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
        """Reserve capacity under BEGIN IMMEDIATE so admission is cross-process atomic."""
        conn = get_connection(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            usage = conn.execute(
                "SELECT COALESCE((SELECT tokens_used FROM token_budget_usage "
                "WHERE client_id = ? AND period = ?), 0) AS used_tokens, "
                "COALESCE((SELECT cost_used_usd FROM token_budget_usage "
                "WHERE client_id = ? AND period = ?), 0) AS used_cost, "
                "COALESCE((SELECT SUM(tokens_reserved) FROM token_budget_reservations "
                "WHERE client_id = ? AND period = ? AND state = 'reserved'), 0) "
                "AS reserved_tokens, "
                "COALESCE((SELECT SUM(cost_reserved_usd) FROM token_budget_reservations "
                "WHERE client_id = ? AND period = ? AND state = 'reserved'), 0) AS reserved_cost",
                (client_id, period, client_id, period, client_id, period, client_id, period),
            ).fetchone()
            token_ok = (
                int(usage["used_tokens"]) + int(usage["reserved_tokens"]) + tokens <= limit_tokens
            )
            cost_ok = (
                limit_cost_usd <= 0
                or float(usage["used_cost"]) + float(usage["reserved_cost"]) + cost_usd
                <= limit_cost_usd
            )
            if not token_ok or not cost_ok:
                conn.rollback()
                return False
            conn.execute(
                "INSERT INTO token_budget_reservations "
                "(reservation_id, client_id, period, tokens_reserved, "
                "cost_reserved_usd, expires_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now', ?))",
                (reservation_id, client_id, period, tokens, cost_usd, f"+{lease_seconds} seconds"),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def settle(self, reservation_id: str, tokens: int, cost_usd: float) -> bool:
        """Settle once, refusing usage outside the atomically admitted envelope.

        The reservation remains present on refusal so the caller can explicitly
        release it.  This keeps committed+reserved within the configured quota
        and makes provider usage contract violations observable.
        """
        conn = get_connection(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            reservation = conn.execute(
                "SELECT client_id, period, tokens_reserved, cost_reserved_usd, state, "
                "expires_at <= datetime('now') AS expired "
                "FROM token_budget_reservations "
                "WHERE reservation_id = ?",
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
                    "UPDATE token_budget_reservations SET state = 'released', "
                    "released_at = datetime('now') WHERE reservation_id = ? AND state = 'reserved'",
                    (reservation_id,),
                )
                conn.commit()
                return False
            if (
                tokens > int(reservation["tokens_reserved"])
                or cost_usd > float(reservation["cost_reserved_usd"]) + 1e-12
            ):
                conn.rollback()
                return False
            conn.execute(
                "INSERT INTO token_budget_usage "
                "(client_id, period, tokens_used, cost_used_usd, last_updated) "
                "VALUES (?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(client_id, period) DO UPDATE SET "
                "tokens_used = tokens_used + excluded.tokens_used, "
                "cost_used_usd = cost_used_usd + excluded.cost_used_usd, "
                "last_updated = datetime('now')",
                (
                    reservation["client_id"],
                    reservation["period"],
                    tokens,
                    cost_usd,
                ),
            )
            conn.execute(
                "UPDATE token_budget_reservations SET state = 'settled', "
                "settled_at = datetime('now') "
                "WHERE reservation_id = ? AND state = 'reserved'",
                (reservation_id,),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release(self, reservation_id: str) -> bool:
        conn = get_connection(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = conn.execute(
                "UPDATE token_budget_reservations SET state = 'released', "
                "released_at = datetime('now') "
                "WHERE reservation_id = ? AND state = 'reserved'",
                (reservation_id,),
            )
            conn.commit()
            return result.rowcount == 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def reconcile_expired_reservations(self) -> int:
        conn = get_connection(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            expired = conn.execute(
                "SELECT reservation_id, client_id FROM token_budget_reservations "
                "WHERE state = 'reserved' AND expires_at <= datetime('now')"
            ).fetchall()
            for reservation in expired:
                reservation_id = reservation["reservation_id"]
                request_id = reservation_id.split(":", 1)[0]
                RequestLogRepository._insert_request(
                    conn,
                    self._orphaned_release_row(request_id, reservation["client_id"]),
                )
                result = conn.execute(
                    "UPDATE token_budget_reservations SET state = 'released', "
                    "released_at = datetime('now') "
                    "WHERE reservation_id = ? AND state = 'reserved'",
                    (reservation_id,),
                )
                if result.rowcount != 1:
                    raise FinalizationConflictError(
                        f"reservation '{reservation_id}' changed during reconciliation"
                    )
                conn.execute(
                    "INSERT INTO stream_finalizations "
                    "(reservation_id, request_id, operation, payload_fingerprint, tokens, cost_usd) "
                    "VALUES (?, ?, 'release', 'lease-expiry-release-v1', 0, 0)",
                    (reservation_id, request_id),
                )
            conn.commit()
            return len(expired)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _orphaned_release_row(request_id: str, client_id: str) -> dict[str, Any]:
        """Minimal durable terminal audit when a crashed request lease expires."""
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
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                "INSERT INTO token_budget_usage "
                "(client_id, period, tokens_used, cost_used_usd, last_updated) "
                "VALUES (?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(client_id, period) DO UPDATE SET "
                "tokens_used = tokens_used + excluded.tokens_used, "
                "cost_used_usd = cost_used_usd + excluded.cost_used_usd, "
                "last_updated = datetime('now')",
                (client_id, period, tokens, cost_usd),
            )
            conn.commit()
        finally:
            conn.close()


class RequestLogRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    @staticmethod
    def _insert_request(conn, row: dict[str, Any]) -> None:  # noqa: ANN001
        conn.execute(
            "INSERT INTO request_logs ("
            "request_id, client_id, model_profile, endpoint, selected_provider, "
            "fallback_used, status, status_code, input_tokens, output_tokens, "
            "estimated_input_tokens, estimated_output_tokens, actual_input_tokens, "
            "actual_output_tokens, usage_source, "
            "estimated_tokens, estimated_cost_usd, cost_saved_usd, "
            "budget_before, budget_after, duration_ms, error_code, error_message, "
            "cache_hit, cache_key, decision_trace, replay_payload, "
            "request_body, response_body"
            ") VALUES ("
            ":request_id, :client_id, :model_profile, :endpoint, :selected_provider, "
            ":fallback_used, :status, :status_code, :input_tokens, :output_tokens, "
            ":estimated_input_tokens, :estimated_output_tokens, :actual_input_tokens, "
            ":actual_output_tokens, :usage_source, "
            ":estimated_tokens, :estimated_cost_usd, :cost_saved_usd, "
            ":budget_before, :budget_after, :duration_ms, :error_code, :error_message, "
            ":cache_hit, :cache_key, :decision_trace, :replay_payload, "
            ":request_body, :response_body"
            ")",
            row,
        )

    @staticmethod
    def _insert_attempt(conn, row: dict[str, Any]) -> None:  # noqa: ANN001
        conn.execute(
            "INSERT INTO provider_attempts ("
            "request_id, provider_id, attempt_order, retry_index, status, "
            "status_code, latency_ms, error_code, error_message, provider_request_id"
            ") VALUES ("
            ":request_id, :provider_id, :attempt_order, :retry_index, :status, "
            ":status_code, :latency_ms, :error_code, :error_message, :provider_request_id"
            ")",
            row,
        )

    def insert_request_with_attempts(
        self, row: dict[str, Any], attempts: list[dict[str, Any]]
    ) -> None:
        """Insert the audit request and every attempt in one transaction."""
        conn = get_connection(self._db_path)
        try:
            conn.execute("BEGIN")
            self._insert_request(conn, row)
            for attempt in attempts:
                self._insert_attempt(conn, attempt)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Compatibility shims for callers outside the application service.
    def insert_request(self, row: dict[str, Any]) -> None:
        self.insert_request_with_attempts(row, [])

    def insert_attempt(self, row: dict[str, Any]) -> None:
        conn = get_connection(self._db_path)
        try:
            self._insert_attempt(conn, row)
            conn.commit()
        finally:
            conn.close()

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM request_logs WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row is None:
                return None
            request = dict(row)

            attempts = conn.execute(
                "SELECT provider_id, attempt_order, retry_index, status, status_code, "
                "latency_ms, error_code, error_message, provider_request_id, created_at "
                "FROM provider_attempts WHERE request_id = ? ORDER BY attempt_order, retry_index",
                (request_id,),
            ).fetchall()
            request["attempts"] = [dict(a) for a in attempts]

            for field in ("decision_trace", "replay_payload", "request_body", "response_body"):
                value = request.get(field)
                if value:
                    with suppress(json.JSONDecodeError, TypeError):
                        request[field] = json.loads(value)
            return request
        finally:
            conn.close()


class SQLiteStreamingFinalizationRepository:
    """Atomically persist a terminal reservation transition and its stream audit."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def get_finalization(self, reservation_id: str) -> FinalizationReceipt | None:
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT f.reservation_id, f.request_id, f.operation, "
                "f.payload_fingerprint, r.state, f.tokens, f.cost_usd, "
                "f.budget_after FROM stream_finalizations f "
                "JOIN token_budget_reservations r ON r.reservation_id = f.reservation_id "
                "WHERE f.reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                return None
            return FinalizationReceipt(
                reservation_id=row["reservation_id"],
                request_id=row["request_id"],
                operation=row["operation"],
                payload_fingerprint=row["payload_fingerprint"],
                state=row["state"],
                tokens=int(row["tokens"]),
                cost_usd=float(row["cost_usd"]),
                budget_after=row["budget_after"],
                already_applied=True,
            )
        finally:
            conn.close()

    def finalize_stream(self, command: FinalizeStreamCommand) -> FinalizationReceipt:
        if command.tokens < 0 or command.cost_usd < 0:
            raise FinalizationRejectedError("stream finalization usage must be non-negative")
        conn = get_connection(self._db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT request_id, operation, payload_fingerprint, tokens, cost_usd, "
                "budget_after "
                "FROM stream_finalizations WHERE reservation_id = ?",
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
                    "SELECT state FROM token_budget_reservations WHERE reservation_id = ?",
                    (command.reservation_id,),
                ).fetchone()["state"]
                conn.commit()
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
            reservation = conn.execute(
                "SELECT client_id, period, tokens_reserved, cost_reserved_usd, state, "
                "expires_at <= datetime('now') AS expired FROM token_budget_reservations "
                "WHERE reservation_id = ?",
                (command.reservation_id,),
            ).fetchone()
            if reservation is None or reservation["state"] != "reserved":
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
                    "INSERT INTO token_budget_usage (client_id, period, tokens_used, cost_used_usd, last_updated) "
                    "VALUES (?, ?, ?, ?, datetime('now')) ON CONFLICT(client_id, period) DO UPDATE SET "
                    "tokens_used=tokens_used+excluded.tokens_used, cost_used_usd=cost_used_usd+excluded.cost_used_usd, last_updated=datetime('now')",
                    (
                        reservation["client_id"],
                        reservation["period"],
                        command.tokens,
                        command.cost_usd,
                    ),
                )
                terminal_state = "settled"
                conn.execute(
                    "UPDATE token_budget_reservations SET state='settled', settled_at=datetime('now') WHERE reservation_id=? AND state='reserved'",
                    (command.reservation_id,),
                )
            else:
                terminal_state = "released"
                conn.execute(
                    "UPDATE token_budget_reservations SET state='released', released_at=datetime('now') WHERE reservation_id=? AND state='reserved'",
                    (command.reservation_id,),
                )
                if command.tokens != 0 or command.cost_usd != 0:
                    raise FinalizationRejectedError(
                        "release finalization must not carry billable usage"
                    )
            usage = conn.execute(
                "SELECT COALESCE((SELECT tokens_used FROM token_budget_usage "
                "WHERE client_id=? AND period=?), 0) AS used",
                (reservation["client_id"], reservation["period"]),
            ).fetchone()
            reserved = conn.execute(
                "SELECT COALESCE(SUM(tokens_reserved), 0) AS reserved FROM token_budget_reservations WHERE client_id=? AND period=? AND state='reserved'",
                (reservation["client_id"], reservation["period"]),
            ).fetchone()
            limit = conn.execute(
                "SELECT budget_max_tokens FROM clients WHERE client_id=?",
                (reservation["client_id"],),
            ).fetchone()["budget_max_tokens"]
            budget_after = max(0, int(limit) - int(usage["used"]) - int(reserved["reserved"]))
            row = dict(command.request_row)
            row["budget_after"] = budget_after
            RequestLogRepository._insert_request(conn, row)
            for attempt in command.attempts:
                RequestLogRepository._insert_attempt(conn, attempt)
            conn.execute(
                "INSERT INTO stream_finalizations (reservation_id, request_id, operation, payload_fingerprint, tokens, cost_usd, budget_after) VALUES (?, ?, ?, ?, ?, ?, ?)",
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
            conn.commit()
            return FinalizationReceipt(
                command.reservation_id,
                command.request_id,
                command.operation,
                command.payload_fingerprint,
                terminal_state,
                command.tokens,
                command.cost_usd,
                budget_after,
                False,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class ConfigEventRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def record(self, event_type: str, detail: str, checksum: str = "") -> None:
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                "INSERT INTO config_events (event_type, detail, checksum) VALUES (?, ?, ?)",
                (event_type, detail, checksum),
            )
            conn.commit()
        finally:
            conn.close()
