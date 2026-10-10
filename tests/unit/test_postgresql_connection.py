from __future__ import annotations

import threading
import time

from app.infrastructure.persistence.postgresql import connection


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
