from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

from app.infrastructure.persistence.postgresql import connection


def test_connection_establishment_metrics_are_low_cardinality_and_credential_free(
    monkeypatch,
) -> None:
    class FakePool:
        max_size = 8

        @staticmethod
        def get_stats() -> dict[str, int]:
            return {
                "connections_num": 3,
                "connections_errors": 1,
                "connections_ms": 50,
                "requests_num": 6,
                "requests_errors": 2,
                "requests_wait_ms": 25,
                "pool_size": 2,
                "pool_available": 1,
                "requests_waiting": 0,
            }

    monkeypatch.setattr(connection, "_POOLS", {"synthetic-url": FakePool()})

    rendered = connection.prometheus("test_gateway")

    assert 'test_gateway_database_connection_establishments_total{result="success"} 2' in rendered
    assert 'test_gateway_database_connection_establishments_total{result="failure"} 1' in rendered
    assert "test_gateway_database_connection_establishment_seconds_count" in rendered
    assert "test_gateway_database_connection_establishment_seconds_sum" in rendered
    assert "test_gateway_database_pool_checkouts_total{result=\"success\"} 4" in rendered
    assert "test_gateway_database_pool_checkout_wait_seconds_total 0.025" in rendered
    assert "database_url" not in rendered


def test_pool_starts_without_blocking_global_lock_on_initial_connection(monkeypatch) -> None:
    class FakePool:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.max_size = kwargs["max_size"]
            self.open_wait = None
            self.open_timeout = None
            self.connection_calls = 0

        def open(self, *, wait: bool = False, timeout=None) -> None:  # noqa: ANN001
            self.open_wait = wait
            self.open_timeout = timeout

        @contextmanager
        def connection(self, *, timeout: float):
            self.connection_calls += 1
            yield "connection"

    pools: dict[str, FakePool] = {}
    monkeypatch.setattr(connection, "_POOLS", pools)
    monkeypatch.setitem(sys.modules, "psycopg_pool", SimpleNamespace(ConnectionPool=FakePool))

    url = "postgresql://gateway:synthetic@127.0.0.1:5432/gateway"
    with connection.connect(url) as leased:
        assert leased == "connection"
    with connection.connect(url) as leased:
        assert leased == "connection"

    pool = pools[url]
    assert pool.open_wait is False
    assert pool.open_timeout is None
    assert pool.connection_calls == 2


def test_connection_parameters_use_numeric_address_and_keep_tls_hostname(monkeypatch) -> None:
    monkeypatch.setattr(
        connection,
        "_resolve_database_address",
        lambda host, port: "192.0.2.10",
    )
    with connection._DNS_LOCK:
        connection._DNS_ADDRESSES.pop(("db-wave5-test.invalid", "5432"), None)

    parameters = connection._connection_parameters(
        "postgresql://gateway:synthetic@db-wave5-test.invalid:5432/gateway?sslmode=verify-full"
    )

    assert parameters["host"] == "db-wave5-test.invalid"
    assert parameters["hostaddr"] == "192.0.2.10"
    assert parameters["sslmode"] == "verify-full"


def test_connection_parameters_preserve_explicit_hostaddr(monkeypatch) -> None:
    def unexpected_resolution(_host: str, _port: str) -> str:
        raise AssertionError("explicit hostaddr must bypass DNS")

    monkeypatch.setattr(connection, "_resolve_database_address", unexpected_resolution)
    parameters = connection._connection_parameters(
        "host=db-wave5-test.invalid hostaddr=192.0.2.20 port=5432 dbname=gateway"
    )

    assert parameters["host"] == "db-wave5-test.invalid"
    assert parameters["hostaddr"] == "192.0.2.20"


def test_failed_connection_dns_refresh_is_deduplicated_and_asynchronous(monkeypatch) -> None:
    key = ("db-refresh-wave5.invalid", "5432")
    completed = threading.Event()

    def resolve(_host: str, _port: str) -> str:
        time.sleep(0.2)
        completed.set()
        return "192.0.2.30"

    monkeypatch.setattr(connection, "_resolve_database_address", resolve)
    with connection._DNS_LOCK:
        connection._DNS_ADDRESSES.pop(key, None)
    started = time.monotonic()
    connection._schedule_database_address_refresh(*key)
    connection._schedule_database_address_refresh(*key)

    assert time.monotonic() - started < 0.1
    assert completed.wait(1)
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        with connection._DNS_LOCK:
            address = connection._DNS_ADDRESSES.get(key)
        if address is not None:
            break
        time.sleep(0.001)
    assert address == "192.0.2.30"
