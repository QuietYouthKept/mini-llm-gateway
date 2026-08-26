"""SQLite repositories for budget usage, request logs, and config events.

Each method opens its own connection, so the repositories are safe to call from
async handlers without shared mutable connection state. For a production
deployment these would be swapped for Postgres; the interfaces stay the same.
"""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

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
                int(usage["used_tokens"])
                + int(usage["reserved_tokens"])
                + tokens
                <= limit_tokens
            )
            cost_ok = (
                limit_cost_usd <= 0
                or float(usage["used_cost"])
                + float(usage["reserved_cost"])
                + cost_usd
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
                "SELECT client_id, period, tokens_reserved, cost_reserved_usd, state "
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
            if tokens > int(reservation["tokens_reserved"]) or cost_usd > float(
                reservation["cost_reserved_usd"]
            ) + 1e-12:
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
            result = conn.execute(
                "UPDATE token_budget_reservations SET state = 'released', "
                "released_at = datetime('now') "
                "WHERE state = 'reserved' AND expires_at <= datetime('now')"
            )
            conn.commit()
            return result.rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
            "status_code, latency_ms, error_code, error_message"
            ") VALUES ("
            ":request_id, :provider_id, :attempt_order, :retry_index, :status, "
            ":status_code, :latency_ms, :error_code, :error_message"
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
                "latency_ms, error_code, error_message, created_at "
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
