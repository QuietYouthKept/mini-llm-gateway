"""Explicit PostgreSQL migration job entrypoint.

Run this as a one-shot deployment job, never as part of API process startup:
``GW_DATABASE_URL=... .venv/Scripts/python scripts/migrate_postgres.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.infrastructure.persistence.postgresql.connection import migrate


def main() -> None:
    database_url = os.environ.get("GW_DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise SystemExit("GW_DATABASE_URL must be a PostgreSQL connection URL")
    migrate(database_url, app_version="1.0.0rc1")
    print("PostgreSQL migrations applied and checksummed")


if __name__ == "__main__":
    main()
