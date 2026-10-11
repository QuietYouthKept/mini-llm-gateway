"""PostgreSQL connection and idempotent migration helpers."""

from __future__ import annotations

import atexit
import hashlib
import ipaddress
import os
import socket
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any

_DNS_LOCK = Lock()
_DNS_REFRESH_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="gateway-postgres-dns"
)
_DNS_REFRESHING: set[tuple[str, str]] = set()
_DNS_ADDRESSES: dict[tuple[str, str], str] = {}
_POOL_LOCK = Lock()
_POOLS: dict[str, Any] = {}
_POOL_DEFAULT_MAX_SIZE = 8
_POOL_DEFAULT_MAX_WAITING = 16
_POOL_DEFAULT_TIMEOUT_SECONDS = 0.25


def prometheus(prefix: str = "llm_gateway") -> str:
    """Expose aggregate, credential-free PostgreSQL pool and connect timings."""
    with _POOL_LOCK:
        pools = tuple(_POOLS.values())
    snapshot: dict[str, float] = {}
    pool_max = pool_size = pool_available = requests_waiting = 0
    for pool in pools:
        try:
            stats = pool.get_stats()
        except Exception:
            continue
        for name, value in stats.items():
            snapshot[name] = snapshot.get(name, 0.0) + float(value)
        pool_max += int(pool.max_size)
        pool_size += int(stats.get("pool_size", 0))
        pool_available += int(stats.get("pool_available", 0))
        requests_waiting += int(stats.get("requests_waiting", 0))
    connections = int(snapshot.get("connections_num", 0))
    connection_errors = int(snapshot.get("connections_errors", 0))
    checkouts = int(snapshot.get("requests_num", 0))
    checkout_errors = int(snapshot.get("requests_errors", 0))
    return "\n".join(
        (
            f"# TYPE {prefix}_database_connection_establishments_total counter",
            f'{prefix}_database_connection_establishments_total{{result="success"}} '
            f"{connections - connection_errors}",
            f'{prefix}_database_connection_establishments_total'
            f'{{result="failure"}} {connection_errors}',
            f"# TYPE {prefix}_database_connection_establishment_seconds summary",
            f"{prefix}_database_connection_establishment_seconds_count {connections}",
            f"{prefix}_database_connection_establishment_seconds_sum "
            f"{snapshot.get('connections_ms', 0.0) / 1000:.6g}",
            f"# TYPE {prefix}_database_pool_checkouts_total counter",
            f'{prefix}_database_pool_checkouts_total{{result="success"}} '
            f"{checkouts - checkout_errors}",
            f'{prefix}_database_pool_checkouts_total{{result="failure"}} {checkout_errors}',
            f"# TYPE {prefix}_database_pool_checkout_wait_seconds_total counter",
            f"{prefix}_database_pool_checkout_wait_seconds_total "
            f"{snapshot.get('requests_wait_ms', 0.0) / 1000:.6g}",
            f"# TYPE {prefix}_database_pool_size gauge",
            f"{prefix}_database_pool_size {pool_size}",
            f"# TYPE {prefix}_database_pool_max_size gauge",
            f"{prefix}_database_pool_max_size {pool_max}",
            f"# TYPE {prefix}_database_pool_available gauge",
            f"{prefix}_database_pool_available {pool_available}",
            f"# TYPE {prefix}_database_pool_requests_waiting gauge",
            f"{prefix}_database_pool_requests_waiting {requests_waiting}",
        )
    ) + "\n"


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


def _connection_kwargs(
    database_url: str,
    *,
    connect_timeout: int = 1,
    statement_timeout_ms: int = 3000,
    lock_timeout_ms: int = 1000,
) -> dict[str, Any]:
    from psycopg.rows import dict_row

    parameters = _connection_parameters(database_url)
    host = parameters.get("host", "")
    if len(host.split(",")) == 1 and host and not parameters.get("hostaddr"):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            _schedule_database_address_refresh(host, parameters.get("port", "5432"))
    parameters["connect_timeout"] = str(max(1, connect_timeout))
    parameters["options"] = (
        f"-c statement_timeout={max(1, statement_timeout_ms)} "
        f"-c lock_timeout={max(1, lock_timeout_ms)} "
        "-c idle_in_transaction_session_timeout=5000"
    )
    parameters["row_factory"] = dict_row
    return parameters


def _pool_for(
    database_url: str,
    *,
    connect_timeout: int = 1,
    statement_timeout_ms: int = 3000,
    lock_timeout_ms: int = 1000,
) -> Any:
    with _POOL_LOCK:
        pool = _POOLS.get(database_url)
        if pool is not None:
            return pool
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - dependency gate
            raise RuntimeError("PostgreSQL pooling requires psycopg[pool]") from exc
        from psycopg.conninfo import conninfo_to_dict

        parameters = conninfo_to_dict(database_url)
        host = parameters.get("host", "")
        port = parameters.get("port", "5432")

        def reconnect_failed(_pool: Any) -> None:
            if host and len(host.split(",")) == 1:
                try:
                    ipaddress.ip_address(host)
                except ValueError:
                    _schedule_database_address_refresh(host, port)

        pool = ConnectionPool(
            conninfo="",
            kwargs=lambda: _connection_kwargs(
                database_url,
                connect_timeout=connect_timeout,
                statement_timeout_ms=statement_timeout_ms,
                lock_timeout_ms=lock_timeout_ms,
            ),
            min_size=1,
            max_size=_pool_max_size(),
            max_waiting=_pool_max_waiting(),
            timeout=_POOL_DEFAULT_TIMEOUT_SECONDS,
            reconnect_timeout=2.0,
            reconnect_failed=reconnect_failed,
            num_workers=1,
            open=False,
            name="mini-llm-gateway-postgresql",
        )
        # Start the connector worker without waiting for a successful initial
        # connection. Waiting here would hold the process-wide pool lock during
        # an outage, serializing every first DB call for up to connect_timeout.
        # Checkouts below remain bounded by the short pool timeout.
        pool.open(wait=False)
        _POOLS[database_url] = pool
        return pool


def _pool_max_size() -> int:
    configured = int(os.getenv("GW_PG_POOL_MAX_SIZE", _POOL_DEFAULT_MAX_SIZE))
    if configured < 1 or configured > 64:
        raise ValueError("GW_PG_POOL_MAX_SIZE must be between 1 and 64")
    return configured


def _pool_max_waiting() -> int:
    configured = int(os.getenv("GW_PG_POOL_MAX_WAITING", _POOL_DEFAULT_MAX_WAITING))
    if configured < 0 or configured > 256:
        raise ValueError("GW_PG_POOL_MAX_WAITING must be between 0 and 256")
    return configured


def close_pools() -> None:
    """Close process-wide PostgreSQL pools after all DB workers are drained."""
    with _POOL_LOCK:
        pools = tuple(_POOLS.values())
        _POOLS.clear()
    for pool in pools:
        pool.close(timeout=5.0)


def close_pool(database_url: str) -> None:
    """Close one application's pool after its blocking-I/O lanes are drained."""
    with _POOL_LOCK:
        pool = _POOLS.pop(database_url, None)
    if pool is not None:
        pool.close(timeout=5.0)


atexit.register(close_pools)


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


@contextmanager
def connect(
    database_url: str,
    *,
    connect_timeout: int = 1,
    statement_timeout_ms: int = 3000,
    lock_timeout_ms: int = 1000,
) -> Iterator[Any]:
    """Lease a bounded reusable connection with commit/rollback context semantics."""
    pool = _pool_for(
        database_url,
        connect_timeout=connect_timeout,
        statement_timeout_ms=statement_timeout_ms,
        lock_timeout_ms=lock_timeout_ms,
    )
    with pool.connection(timeout=_POOL_DEFAULT_TIMEOUT_SECONDS) as connection:
        yield connection


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
