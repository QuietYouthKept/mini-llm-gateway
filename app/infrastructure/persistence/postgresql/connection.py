"""PostgreSQL connection and idempotent migration helpers."""

from __future__ import annotations

from pathlib import Path


def connect(database_url: str):  # noqa: ANN201
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - environment gate
        raise RuntimeError("PostgreSQL backend requires psycopg[binary]") from exc
    return psycopg.connect(database_url, row_factory=dict_row)


def migrate(database_url: str) -> None:
    root = Path(__file__).resolve().parents[4]
    paths = sorted((root / "migrations" / "postgresql").glob("*.sql"))
    if not paths:
        raise RuntimeError("No PostgreSQL migrations found")
    with connect(database_url) as conn:
        # Multiple replicas may boot simultaneously. Serialize DDL so
        # CREATE OR REPLACE cannot race in PostgreSQL system catalogs.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('mini-llm-gateway-migrations'))")
        for path in paths:
            conn.execute(path.read_text(encoding="utf-8"), prepare=False)
