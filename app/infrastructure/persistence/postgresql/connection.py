"""PostgreSQL connection and idempotent migration helpers."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

_DNS_LOCK = Lock()
_DNS_REFRESH_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="gateway-postgres-dns"
)
_DNS_REFRESHING: set[tuple[str, str]] = set()
_DNS_ADDRESSES: dict[tuple[str, str], str] = {}
_CONNECTION_STATS_LOCK = Lock()
_CONNECTION_STATS = {
    "success": 0,
    "failure": 0,
    "seconds_total": 0.0,
    "seconds_max": 0.0,
}


def prometheus(prefix: str = "llm_gateway") -> str:
    """Expose bounded, credential-free PostgreSQL connection timings."""
    with _CONNECTION_STATS_LOCK:
        snapshot = dict(_CONNECTION_STATS)
    total = snapshot["success"] + snapshot["failure"]
    return "\n".join(
        (
            f"# TYPE {prefix}_database_connection_establishments_total counter",
            f'{prefix}_database_connection_establishments_total'
            f'{{result="success"}} {snapshot["success"]}',
            f'{prefix}_database_connection_establishments_total'
            f'{{result="failure"}} {snapshot["failure"]}',
            f"# TYPE {prefix}_database_connection_establishment_seconds summary",
            f"{prefix}_database_connection_establishment_seconds_count {total}",
            f"{prefix}_database_connection_establishment_seconds_sum "
            f"{snapshot['seconds_total']:.6g}",
            f"{prefix}_database_connection_establishment_seconds_max {snapshot['seconds_max']:.6g}",
        )
    ) + "\n"


def _record_connection_result(result: str, duration: float) -> None:
    with _CONNECTION_STATS_LOCK:
        _CONNECTION_STATS[result] += 1
        _CONNECTION_STATS["seconds_total"] += duration
        _CONNECTION_STATS["seconds_max"] = max(
            _CONNECTION_STATS["seconds_max"], duration
        )


def _resolve_database_address(host: str, port: str) -> str:
    results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not results:
        raise OSError(f"No address returned for database host '{host}'")
    return results[0][4][0]


def _refresh_database_address(host: str, port: str) -> None:
    key = (host.lower(), port)
    try:
        address = _resolve_database_address(host, port)
    except OSError:
        return
    with _DNS_LOCK:
        _DNS_ADDRESSES[key] = address


def _schedule_database_address_refresh(host: str, port: str) -> None:
    key = (host.lower(), port)
    with _DNS_LOCK:
        if key in _DNS_REFRESHING:
            return
        _DNS_REFRESHING.add(key)
    future = _DNS_REFRESH_EXECUTOR.submit(_refresh_database_address, host, port)

    def finished(_future) -> None:  # noqa: ANN001
        with _DNS_LOCK:
            _DNS_REFRESHING.discard(key)

    future.add_done_callback(finished)


def _connection_parameters(database_url: str) -> dict[str, str]:
    """Resolve a single DNS host once and retain its address for fast outages.

    libpq's connect_timeout does not bound the system resolver. Keeping the
    hostname for TLS verification while supplying hostaddr avoids a resolver
    stall on every request. A failed connection schedules one bounded,
    background refresh; it never blocks the request on DNS.
    """
    from psycopg.conninfo import conninfo_to_dict

    parameters = conninfo_to_dict(database_url)
    host = parameters.get("host", "")
    hosts = host.split(",")
    if (
        len(hosts) != 1
        or not host
        or parameters.get("hostaddr")
        or host.startswith("/")
    ):
        return parameters
    try:
        ipaddress.ip_address(host)
    except ValueError:
        port = parameters.get("port", "5432")
        key = (host.lower(), port)
        with _DNS_LOCK:
            address = _DNS_ADDRESSES.get(key)
        if address is None:
            address = _resolve_database_address(host, port)
            with _DNS_LOCK:
                _DNS_ADDRESSES[key] = address
        parameters["hostaddr"] = address
    return parameters


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


def connect(
    database_url: str,
    *,
    connect_timeout: int = 1,
    statement_timeout_ms: int = 3000,
    lock_timeout_ms: int = 1000,
):  # noqa: ANN201
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - environment gate
        raise RuntimeError("PostgreSQL backend requires psycopg[binary]") from exc
    started = time.monotonic()
    # Bound both network establishment and server-side waits.  A Python
    # executor protects the event loop, but without server deadlines a finite
    # worker lane could remain pinned forever by a lock or stalled query.
    try:
        parameters = _connection_parameters(database_url)
    except BaseException:
        _record_connection_result("failure", time.monotonic() - started)
        raise
    host = parameters.get("host", "")
    if len(host.split(",")) == 1 and host and not parameters.get("hostaddr"):
        # _connection_parameters leaves explicit IPs and Unix sockets alone;
        # resolve only DNS names and cache the successful result above.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            port = parameters.get("port", "5432")
            key = (host.lower(), port)
            with _DNS_LOCK:
                cached_address = _DNS_ADDRESSES.get(key)
            if cached_address is None:
                _schedule_database_address_refresh(host, port)
    parameters["connect_timeout"] = str(max(1, connect_timeout))
    parameters["options"] = (
        f"-c statement_timeout={max(1, statement_timeout_ms)} "
        f"-c lock_timeout={max(1, lock_timeout_ms)} "
        "-c idle_in_transaction_session_timeout=5000"
    )
    try:
        connection = psycopg.connect(**parameters, row_factory=dict_row)
    except psycopg.OperationalError:
        if host and len(host.split(",")) == 1:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                _schedule_database_address_refresh(host, parameters.get("port", "5432"))
        _record_connection_result("failure", time.monotonic() - started)
        raise
    except BaseException:
        _record_connection_result("failure", time.monotonic() - started)
        raise
    _record_connection_result("success", time.monotonic() - started)
    return connection


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


def schema_is_current(
    database_url: str,
    *,
    connect_timeout: int = 1,
    statement_timeout_ms: int = 3000,
    lock_timeout_ms: int = 1000,
) -> bool:
    """Return false for an unreachable, incomplete, or checksum-mismatched schema."""
    try:
        expected = {path.stem: _accepted_checksums(path) for path in _migration_paths()}
        with connect(
            database_url,
            connect_timeout=connect_timeout,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
        ) as conn:
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
