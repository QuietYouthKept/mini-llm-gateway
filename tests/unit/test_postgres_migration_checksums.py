"""Portable migration-ledger checksum tests that do not require PostgreSQL."""

from __future__ import annotations

from app.infrastructure.persistence.postgresql.connection import _checksum


def test_postgres_migration_checksum_normalizes_line_endings(tmp_path) -> None:
    lf = tmp_path / "lf.sql"
    crlf = tmp_path / "crlf.sql"
    lf.write_bytes(b"CREATE TABLE example (id integer);\n-- comment\n")
    crlf.write_bytes(b"CREATE TABLE example (id integer);\r\n-- comment\r\n")

    assert _checksum(lf) == _checksum(crlf)
