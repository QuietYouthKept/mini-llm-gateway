from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.application.services.blocking_io import (
    BlockingIOOverloadedError,
    BoundedBlockingIO,
    DependencyCircuitOpenError,
)
from app.infrastructure.observability.tracing import TraceRecorder


@pytest.mark.asyncio
async def test_blocking_operation_does_not_pin_event_loop() -> None:
    io = BoundedBlockingIO(max_workers=1, max_in_flight=1)
    gate = threading.Event()
    try:
        operation = asyncio.create_task(io.run(lambda: (gate.wait(1), "finished")[1]))
        await asyncio.sleep(0.02)
        started = time.monotonic()
        await asyncio.sleep(0)
        assert time.monotonic() - started < 0.05
        gate.set()
        assert await operation == "finished"
    finally:
        gate.set()
        await io.aclose()


@pytest.mark.asyncio
async def test_cancellation_drains_in_flight_worker_before_propagating() -> None:
    io = BoundedBlockingIO(max_workers=1, max_in_flight=1)
    gate = threading.Event()
    finished = threading.Event()

    def work() -> str:
        gate.wait(1)
        finished.set()
        return "committed"

    try:
        operation = asyncio.create_task(io.run(work))
        await asyncio.sleep(0.02)
        operation.cancel()
        await asyncio.sleep(0.02)
        assert not operation.done()
        assert not finished.is_set()
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert finished.is_set()
    finally:
        gate.set()
        await io.aclose()


@pytest.mark.asyncio
async def test_executor_admission_is_bounded_during_dependency_outage() -> None:
    io = BoundedBlockingIO(
        max_workers=1, max_in_flight=1, admission_timeout_seconds=0.02
    )
    gate = threading.Event()
    try:
        operation = asyncio.create_task(io.run(gate.wait, 1))
        await asyncio.sleep(0.02)
        with pytest.raises(BlockingIOOverloadedError):
            await io.run(lambda: None)
        gate.set()
        await operation
    finally:
        gate.set()
        await io.aclose()


@pytest.mark.asyncio
async def test_database_outage_does_not_starve_redis_lane_or_event_loop() -> None:
    io = BoundedBlockingIO(
        max_workers=3,
        max_in_flight=3,
        lane_workers={"database": 1, "redis": 1, "default": 1},
        lane_in_flight={"database": 1, "redis": 1, "default": 1},
    )
    gate = threading.Event()
    started = threading.Event()

    def blocked_database() -> None:
        started.set()
        gate.wait(1)

    try:
        database = asyncio.create_task(io.run(blocked_database, dependency="database"))
        assert await asyncio.to_thread(started.wait, 1)
        ticker_started = time.monotonic()
        assert await io.run(lambda: "redis-ok", dependency="redis") == "redis-ok"
        assert time.monotonic() - ticker_started < 0.2
        assert io.snapshot()["lanes"]["database"]["active_workers"] == 1
        assert io.snapshot()["lanes"]["redis"]["active_workers"] == 0
    finally:
        gate.set()
        await database
        await io.aclose()


@pytest.mark.asyncio
async def test_finalization_lane_runs_while_regular_database_lane_is_saturated() -> None:
    io = BoundedBlockingIO(
        max_workers=3,
        max_in_flight=3,
        admission_timeout_seconds=0.02,
        lane_workers={"database": 1, "database_finalization": 1, "default": 1},
        lane_in_flight={"database": 1, "database_finalization": 1, "default": 1},
    )
    gate = threading.Event()
    started = threading.Event()

    def blocked_query() -> None:
        started.set()
        gate.wait(1)

    operation = asyncio.create_task(io.run(blocked_query, dependency="database"))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        assert await io.run(
            lambda: "finalized",
            dependency="database",
            lane="database_finalization",
        ) == "finalized"
        with pytest.raises(BlockingIOOverloadedError):
            await io.run(lambda: None, dependency="database")
        snapshot = io.snapshot()["lanes"]
        assert snapshot["database"]["active_workers"] == 1
        assert snapshot["database_finalization"]["active_workers"] == 0
        assert snapshot["database"]["admission_rejects_total"] == 1
    finally:
        gate.set()
        await operation
        await io.aclose()


@pytest.mark.asyncio
async def test_worker_exception_propagates_and_releases_executor_slot() -> None:
    io = BoundedBlockingIO(max_workers=1, max_in_flight=1)
    try:
        with pytest.raises(ValueError, match="synthetic failure"):
            await io.run(lambda: (_ for _ in ()).throw(ValueError("synthetic failure")))
        assert await io.run(lambda: "slot released") == "slot released"
    finally:
        await io.aclose()


@pytest.mark.asyncio
async def test_close_is_idempotent_and_rejects_future_work() -> None:
    io = BoundedBlockingIO(max_workers=1, max_in_flight=1)
    await io.aclose()
    await io.aclose()
    with pytest.raises(RuntimeError, match="closed"):
        await io.run(lambda: None)


def test_executor_rejects_an_unbounded_queue_configuration() -> None:
    with pytest.raises(ValueError, match="max_in_flight"):
        BoundedBlockingIO(max_workers=2, max_in_flight=1)


@pytest.mark.asyncio
async def test_queued_database_call_fast_fails_after_connection_failure() -> None:
    io = BoundedBlockingIO(
        max_workers=1,
        max_in_flight=2,
        admission_timeout_seconds=0.05,
        dependency_recovery_seconds=0.03,
    )
    gate = threading.Event()
    started = threading.Event()
    later_call: list[str] = []

    def unavailable() -> None:
        started.set()
        gate.wait(1)
        raise ConnectionError("postgres is unavailable")

    def queued_query() -> str:
        later_call.append("ran")
        return "unexpected"

    first = asyncio.create_task(io.run(unavailable, dependency="database"))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        second = asyncio.create_task(io.run(queued_query, dependency="database"))
        await asyncio.sleep(0.01)
        gate.set()
        with pytest.raises(ConnectionError, match="unavailable"):
            await first
        with pytest.raises(DependencyCircuitOpenError):
            await second
        assert later_call == []

        with pytest.raises(DependencyCircuitOpenError):
            await io.run(queued_query, dependency="database")
        assert later_call == []

        await asyncio.sleep(0.04)
        assert await io.run(lambda: "healthy", dependency="database", probe=True) == "healthy"
        io.report_dependency_success("database")
        assert await io.run(queued_query, dependency="database") == "unexpected"
        assert later_call == ["ran"]
    finally:
        gate.set()
        await io.aclose()


def test_chat_service_does_not_classify_executor_saturation_as_database_outage(container) -> None:
    classifier = container.chat_service._is_database_unavailable
    assert not classifier(BlockingIOOverloadedError("synthetic saturation"))
    assert classifier(DependencyCircuitOpenError("postgres circuit is open"))
    assert classifier(ConnectionError("synthetic connection failure"))
    assert not classifier(RuntimeError("unrelated application error"))


@pytest.mark.asyncio
async def test_blocking_io_records_low_cardinality_operation_span() -> None:
    io = BoundedBlockingIO(max_workers=1, max_in_flight=1)
    tracer = TraceRecorder()
    io.tracer = tracer

    def operation() -> str:
        return "ok"

    try:
        assert await io.run(operation, dependency="database") == "ok"
        span = tracer.snapshot()[0]
        assert span.name == "blocking_io.operation"
        assert span.attributes == {
            "blocking_io.lane": "default",
            "blocking_io.operation": BoundedBlockingIO._operation_name(operation),
            "dependency.name": "database",
        }
        assert span.status == "ok"
        assert span.duration_ms >= 0
    finally:
        await io.aclose()
