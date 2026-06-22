from __future__ import annotations

import sqlite3
from pathlib import Path

from app.infrastructure.persistence.sqlite.schema import SCHEMA_SQL, SCHEMA_VERSION


def get_connection(db_path: str) -> sqlite3.Connection:
    """Return a SQLite connection for the given path.

    Creates parent directories if needed and enables WAL mode + foreign keys.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> None:
    """Run schema migration and ensure all tables exist."""
    conn = get_connection(db_path)
    try:
        # Ensure schema_migrations table exists first
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version INTEGER PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        cursor = conn.execute(
            "SELECT MAX(version) FROM schema_migrations"
        )
        row = cursor.fetchone()
        current_version = row[0] if row and row[0] else 0

        if current_version < SCHEMA_VERSION:
            conn.executescript(SCHEMA_SQL)
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            conn.commit()
    finally:
        conn.close()
