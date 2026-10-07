from __future__ import annotations

import sqlite3
from pathlib import Path

from app.infrastructure.persistence.sqlite.schema import SCHEMA_SQL, SCHEMA_VERSION


def get_connection(db_path: str) -> sqlite3.Connection:
    """Return a SQLite connection for the given path.

    Creates parent directories if needed and enables WAL mode + foreign keys.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


# Columns added after the initial schema, applied idempotently to existing DBs.
_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("request_logs", "cost_saved_usd", "cost_saved_usd REAL NOT NULL DEFAULT 0"),
    ("request_logs", "cache_hit", "cache_hit INTEGER NOT NULL DEFAULT 0"),
    ("request_logs", "cache_key", "cache_key TEXT"),
    ("request_logs", "decision_trace", "decision_trace TEXT"),
    ("request_logs", "replay_payload", "replay_payload TEXT"),
    (
        "request_logs",
        "estimated_input_tokens",
        "estimated_input_tokens INTEGER NOT NULL DEFAULT 0",
    ),
    (
        "token_budget_reservations",
        "state",
        "state TEXT NOT NULL DEFAULT 'reserved'",
    ),
    ("token_budget_reservations", "expires_at", "expires_at TEXT"),
    ("token_budget_reservations", "settled_at", "settled_at TEXT"),
    ("token_budget_reservations", "released_at", "released_at TEXT"),
    (
        "request_logs",
        "estimated_output_tokens",
        "estimated_output_tokens INTEGER NOT NULL DEFAULT 0",
    ),
    ("request_logs", "actual_input_tokens", "actual_input_tokens INTEGER"),
    ("request_logs", "actual_output_tokens", "actual_output_tokens INTEGER"),
    (
        "request_logs",
        "usage_source",
        "usage_source TEXT NOT NULL DEFAULT 'estimated'",
    ),
    ("provider_attempts", "provider_request_id", "provider_request_id TEXT"),
]


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db(db_path: str) -> None:
    """Run schema migration and ensure all tables/columns exist."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version INTEGER PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        current_version = row[0] if row and row[0] else 0

        if current_version < SCHEMA_VERSION:
            conn.executescript(SCHEMA_SQL)
            for table, column, ddl in _COLUMN_MIGRATIONS:
                _ensure_column(conn, table, column, ddl)
            conn.execute(
                "UPDATE token_budget_reservations SET state = COALESCE(state, 'reserved'), "
                "expires_at = COALESCE(expires_at, datetime('now', '+30 seconds'))"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_budget_reservations_expiry "
                "ON token_budget_reservations(state, expires_at)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            conn.commit()
    finally:
        conn.close()
