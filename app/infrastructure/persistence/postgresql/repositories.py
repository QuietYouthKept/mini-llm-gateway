"""PostgreSQL repositories implementing the Gateway persistence ports."""

from __future__ import annotations

import json
from typing import Any

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
                """SELECT client_id, period, tokens_reserved, cost_reserved_usd, state
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
            if tokens > reservation["tokens_reserved"] or cost_usd > float(
                reservation["cost_reserved_usd"]
            ) + 1e-12:
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
            result = conn.execute(
                "UPDATE token_budget_reservations SET state='released', released_at=now() "
                "WHERE state='reserved' AND expires_at <= now()"
            )
            return result.rowcount

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
        "request_id", "client_id", "model_profile", "endpoint", "selected_provider",
        "fallback_used", "status", "status_code", "input_tokens", "output_tokens",
        "estimated_input_tokens", "estimated_output_tokens", "actual_input_tokens",
        "actual_output_tokens", "usage_source", "estimated_tokens", "estimated_cost_usd",
        "cost_saved_usd", "budget_before", "budget_after", "duration_ms", "error_code",
        "error_message", "cache_hit", "cache_key", "decision_trace", "replay_payload",
        "request_body", "response_body",
    )

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def insert_request_with_attempts(
        self, row: dict[str, Any], attempts: list[dict[str, Any]]
    ) -> None:
        columns = ",".join(self._REQUEST_COLUMNS)
        placeholders = ",".join(["%s"] * len(self._REQUEST_COLUMNS))
        values = [row[column] for column in self._REQUEST_COLUMNS]
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
        with connect(self._database_url) as conn:
            conn.execute(f"INSERT INTO request_logs ({columns}) VALUES ({placeholders})", values)
            for attempt in attempts:
                conn.execute(
                    """INSERT INTO provider_attempts
                    (request_id,provider_id,attempt_order,retry_index,status,status_code,
                     latency_ms,error_code,error_message)
                    VALUES (%(request_id)s,%(provider_id)s,%(attempt_order)s,%(retry_index)s,
                    %(status)s,%(status_code)s,%(latency_ms)s,%(error_code)s,%(error_message)s)""",
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
                    latency_ms,error_code,error_message,created_at FROM provider_attempts
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


class PostgresConfigEventRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def record(self, event_type: str, detail: str, checksum: str = "") -> None:
        with connect(self._database_url) as conn:
            conn.execute(
                "INSERT INTO config_events (event_type,detail,checksum) VALUES (%s,%s,%s)",
                (event_type, detail, checksum),
            )
