from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from app.infrastructure.persistence.sqlite.schema import SCHEMA_SQL, SCHEMA_VERSION


def schema_checksum() -> str:
    """Checksum the schema bundle recorded in the SQLite migration ledger."""
    return hashlib.sha256(SCHEMA_SQL.encode("utf-8")).hexdigest()


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
            "  checksum TEXT,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now')),"
            "  app_version TEXT,"
            "  duration_ms INTEGER"
            ")"
        )
        _ensure_column(conn, "schema_migrations", "checksum", "checksum TEXT")
        _ensure_column(conn, "schema_migrations", "app_version", "app_version TEXT")
        _ensure_column(conn, "schema_migrations", "duration_ms", "duration_ms INTEGER")
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        current_version = row[0] if row and row[0] else 0

        if current_version < SCHEMA_VERSION:
            started = time.monotonic()
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
                """
                INSERT OR REPLACE INTO schema_migrations
                (version, checksum, app_version, duration_ms)
                VALUES (?, ?, ?, ?)
                """,
                (
                    SCHEMA_VERSION,
                    schema_checksum(),
                    "1.0.0rc1",
                    int((time.monotonic() - started) * 1000),
                ),
            )
            conn.commit()
        else:
            recorded = conn.execute(
                "SELECT checksum FROM schema_migrations WHERE version = ?", (SCHEMA_VERSION,)
            ).fetchone()
            # Pre-ledger local databases are backfilled once. A populated but
            # different checksum means the installed schema bundle changed
            # without a migration version bump and must not receive traffic.
            if recorded and recorded[0] and recorded[0] != schema_checksum():
                raise RuntimeError("SQLite schema migration checksum mismatch")
            if recorded and not recorded[0]:
                conn.execute(
                    "UPDATE schema_migrations SET checksum = ?, app_version = ?, duration_ms = 0 "
                    "WHERE version = ?",
                    (schema_checksum(), "1.0.0rc1", SCHEMA_VERSION),
                )
                conn.commit()
    finally:
        conn.close()
