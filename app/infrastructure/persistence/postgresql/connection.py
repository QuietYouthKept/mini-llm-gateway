"""PostgreSQL connection and idempotent migration helpers."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path


def _migration_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[4]
    paths = sorted((root / "migrations" / "postgresql").glob("*.sql"))
    if not paths:
        raise RuntimeError("No PostgreSQL migrations found")
    return paths


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_ledger(conn) -> None:  # noqa: ANN001
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version text PRIMARY KEY,
            checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now(),
            app_version text NOT NULL,
            duration_ms integer NOT NULL CHECK (duration_ms >= 0)
        )
        """
    )


def connect(database_url: str):  # noqa: ANN201
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - environment gate
        raise RuntimeError("PostgreSQL backend requires psycopg[binary]") from exc
    return psycopg.connect(database_url, row_factory=dict_row)


def migrate(database_url: str, *, app_version: str = "unknown") -> None:
    """Apply immutable, checksummed migrations under a cluster-wide DDL lock."""
    paths = _migration_paths()
    with connect(database_url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('mini-llm-gateway-migrations'))")
        _ensure_ledger(conn)
        for path in paths:
            version = path.stem
            checksum = _checksum(path)
            row = conn.execute(
                "SELECT checksum FROM schema_migrations WHERE version = %s", (version,)
            ).fetchone()
            if row:
                stored = row["checksum"] if isinstance(row, dict) else row[0]
                if stored != checksum:
                    raise RuntimeError(
                        f"Migration checksum mismatch for {version}; "
                        "published migrations are immutable"
                    )
                continue
            started = time.monotonic()
            conn.execute(path.read_text(encoding="utf-8"), prepare=False)
            conn.execute(
                """
                INSERT INTO schema_migrations(version, checksum, app_version, duration_ms)
                VALUES (%s, %s, %s, %s)
                """,
                (version, checksum, app_version, int((time.monotonic() - started) * 1000)),
            )


def schema_is_current(database_url: str) -> bool:
    """Return false for an unreachable, incomplete, or checksum-mismatched schema."""
    try:
        expected = {path.stem: _checksum(path) for path in _migration_paths()}
        with connect(database_url) as conn:
            rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
        applied = {
            (row["version"] if isinstance(row, dict) else row[0]): (
                row["checksum"] if isinstance(row, dict) else row[1]
            )
            for row in rows
        }
        return applied == expected
    except Exception:
        return False
