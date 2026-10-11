from __future__ import annotations

import asyncio
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg_pool import PoolTimeout, TooManyRequests

from app.application.services.blocking_io import BoundedBlockingIO
from app.infrastructure.persistence.postgresql import connection as pg_connection
from app.infrastructure.persistence.postgresql.connection import close_pool, connect

DATABASE_URL = os.getenv("GATEWAY_POSTGRES_URL") or os.getenv("WAVE3_POSTGRES_URL")


def _unique_application_url(label: str) -> str:
    assert DATABASE_URL is not None
    parameters = conninfo_to_dict(DATABASE_URL)
    parameters["application_name"] = f"wave5-{label}-{uuid4().hex[:10]}"
    return make_conninfo(**parameters)


@pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL service is not configured")
def test_postgresql_pool_admission_is_bounded_under_contention(monkeypatch) -> None:
    assert DATABASE_URL is not None
    monkeypatch.setenv("GW_PG_POOL_MAX_SIZE", "2")
    monkeypatch.setenv("GW_PG_POOL_MAX_WAITING", "2")
    url = _unique_application_url("pool")
    barrier = threading.Barrier(8)

    def query(index: int) -> int:
        barrier.wait(timeout=2)
        with connect(url) as connection:
            connection.execute("SELECT pg_sleep(0.3)")
            return index

    completed: list[int] = []
    rejected: list[BaseException] = []
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(query, index) for index in range(8)]
            for future in as_completed(futures, timeout=5):
                try:
                    completed.append(future.result())
                except (PoolTimeout, TooManyRequests) as exc:
                    rejected.append(exc)

        assert completed
        assert rejected
        assert len(completed) + len(rejected) == 8
        pool_stats = pg_connection._POOLS[url].get_stats()
        assert pool_stats["pool_size"] <= 2
        assert pool_stats["requests_waiting"] == 0
        assert pool_stats["requests_errors"] >= len(rejected)
    finally:
        close_pool(url)


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL service is not configured")
async def test_cancellation_drains_real_postgresql_worker_before_propagating() -> None:
    assert DATABASE_URL is not None
    started = threading.Event()
    io = BoundedBlockingIO(max_workers=1, max_in_flight=1)

    def slow_query() -> int:
        started.set()
        with connect(DATABASE_URL) as connection:
            return connection.execute("SELECT pg_sleep(0.35), 7").fetchone()["?column?"]

    try:
        task = asyncio.create_task(io.run(slow_query, dependency="database"))
        assert await asyncio.to_thread(started.wait, 2)
        await asyncio.sleep(0.05)
        cancel_started = time.monotonic()
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done(), "cancellation must wait for the non-cancellable DB worker"
        with pytest.raises(asyncio.CancelledError):
            await task
        assert time.monotonic() - cancel_started >= 0.20

        with connect(DATABASE_URL) as connection:
            assert connection.execute("SELECT 7").fetchone()["?column?"] == 7
    finally:
        await io.aclose()


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL service is not configured")
async def test_lock_and_statement_timeouts_are_request_scoped_not_database_outage() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    table = f"wave5_lock_probe_{suffix}"
    admin_url = _unique_application_url("lock-admin")
    holder_url = _unique_application_url("lock-holder")
    conflict_url = _unique_application_url("lock-conflict")
    timeout_url = _unique_application_url("timeout")
    with connect(admin_url) as connection:
        connection.execute(f'CREATE TABLE "{table}" (id integer PRIMARY KEY, value integer)')
        connection.execute(f'INSERT INTO "{table}" VALUES (1, 0)')

    locked = threading.Event()
    release = threading.Event()
    io = BoundedBlockingIO(max_workers=2, max_in_flight=2)

    def hold_row_lock() -> None:
        with connect(holder_url, lock_timeout_ms=5000) as connection:
            connection.execute(f'UPDATE "{table}" SET value = value + 1 WHERE id = 1')
            locked.set()
            assert release.wait(3)

    def conflict_on_row() -> None:
        with connect(conflict_url, lock_timeout_ms=100) as connection:
            connection.execute(f'UPDATE "{table}" SET value = value + 1 WHERE id = 1')

    holder = ThreadPoolExecutor(max_workers=1)
    holding = holder.submit(hold_row_lock)
    try:
        assert await asyncio.to_thread(locked.wait, 2)
        with pytest.raises(psycopg.errors.LockNotAvailable) as lock_error:
            await io.run(conflict_on_row, dependency="database")
        assert lock_error.value.sqlstate == "55P03"

        def statement_timeout() -> None:
            with connect(timeout_url, statement_timeout_ms=100) as connection:
                connection.execute("SELECT pg_sleep(0.4)")

        with pytest.raises(psycopg.errors.QueryCanceled) as timeout_error:
            await io.run(statement_timeout, dependency="database")
        assert timeout_error.value.sqlstate == "57014"
        assert not io.dependency_circuit_open("database")
    finally:
        release.set()
        holding.result(timeout=3)
        holder.shutdown(wait=True)
        await io.aclose()
        with connect(admin_url) as connection:
            connection.execute(f'DROP TABLE IF EXISTS "{table}"')


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL service is not configured")
async def test_real_postgresql_deadlock_is_reported_without_opening_outage_circuit() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex[:12]
    table = f"wave5_deadlock_probe_{suffix}"
    url = _unique_application_url("deadlock")
    admin_url = _unique_application_url("deadlock-admin")
    with connect(admin_url) as connection:
        connection.execute(f'CREATE TABLE "{table}" (id integer PRIMARY KEY, value integer)')
        connection.execute(f'INSERT INTO "{table}" VALUES (1, 0), (2, 0)')

    barrier = threading.Barrier(2)
    io = BoundedBlockingIO(max_workers=2, max_in_flight=2)

    def transaction(first: int, second: int) -> str:
        with connect(url, lock_timeout_ms=5000) as connection:
            connection.execute(f'UPDATE "{table}" SET value = value + 1 WHERE id = %s', (first,))
            barrier.wait(timeout=3)
            connection.execute(f'UPDATE "{table}" SET value = value + 1 WHERE id = %s', (second,))
        return "committed"

    async def run_transaction(first: int, second: int) -> str:
        try:
            return await io.run(transaction, first, second, dependency="database")
        except psycopg.errors.DeadlockDetected as exc:
            return f"deadlock:{exc.sqlstate}"

    try:
        results = await asyncio.gather(run_transaction(1, 2), run_transaction(2, 1))
        assert results.count("committed") == 1
        assert results.count("deadlock:40P01") == 1
        assert not io.dependency_circuit_open("database")
    finally:
        with connect(admin_url) as connection:
            connection.execute(f'DROP TABLE IF EXISTS "{table}"')
        await io.aclose()
