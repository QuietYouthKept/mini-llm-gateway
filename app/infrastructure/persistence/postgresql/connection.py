"""PostgreSQL connection and idempotent migration helpers."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path


def _migration_paths() -> list[Path]:
    configured_path = os.getenv("GW_MIGRATIONS_PATH", "").strip()
    if configured_path:
        migration_directory = Path(configured_path)
    else:
        root = Path(__file__).resolve().parents[4]
        migration_directory = root / "migrations" / "postgresql"
    paths = sorted(migration_directory.glob("*.sql"))
    if not paths:
        raise RuntimeError("No PostgreSQL migrations found")
    return paths


def _checksum(path: Path) -> str:
    """Hash canonical SQL bytes so Git's CRLF conversion cannot fork a ledger."""
    return hashlib.sha256(_canonical_migration_bytes(path)).hexdigest()


def _legacy_checksum(path: Path) -> str:
    """Recognize ledgers created before checksums were newline-normalized."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_migration_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _accepted_checksums(path: Path) -> set[str]:
    """Canonical checksum plus the pre-0.4 raw-byte form for safe upgrades."""
    return {_checksum(path), _legacy_checksum(path)}


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
    return psycopg.connect(database_url, connect_timeout=2, row_factory=dict_row)


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
                if stored not in _accepted_checksums(path):
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
        expected = {path.stem: _accepted_checksums(path) for path in _migration_paths()}
        with connect(database_url) as conn:
            rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
        applied = {
            (row["version"] if isinstance(row, dict) else row[0]): (
                row["checksum"] if isinstance(row, dict) else row[1]
            )
            for row in rows
        }
        return set(applied) == set(expected) and all(
            applied[version] in checksums for version, checksums in expected.items()
        )
    except Exception:
        return False
