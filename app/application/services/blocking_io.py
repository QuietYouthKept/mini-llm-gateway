"""Bounded bridge for synchronous database and Redis clients.

Repository ports are intentionally synchronous today.  Async request handlers
must route those calls through this adapter so an outage cannot pin the ASGI
event loop.  Cancellation is deferred until an already-running operation has
finished: Python cannot stop a worker thread, and returning early from a write
could otherwise make its commit outcome appear known when it is not.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic
from typing import Any, TypeVar

T = TypeVar("T")


class BlockingIOOverloadedError(RuntimeError):
    """Raised when the bounded synchronous-I/O lane cannot admit more work."""


class DependencyCircuitOpenError(BlockingIOOverloadedError):
    """Raised before submitting more work to a dependency known to be down."""


class BoundedBlockingIO:
    def __init__(
        self,
        *,
        max_workers: int = 8,
        max_in_flight: int = 16,
        admission_timeout_seconds: float = 0.25,
        dependency_recovery_seconds: float = 1.0,
        lane_workers: dict[str, int] | None = None,
        lane_in_flight: dict[str, int] | None = None,
    ) -> None:
        if (
            max_workers < 1
            or max_in_flight < max_workers
            or admission_timeout_seconds <= 0
            or dependency_recovery_seconds <= 0
        ):
            raise ValueError(
                "max_workers must be positive and max_in_flight must be >= max_workers; "
                "timeouts must also be positive"
            )
        workers_by_lane = lane_workers or {"default": max_workers}
        if (
            "default" not in workers_by_lane
            or any(workers < 1 for workers in workers_by_lane.values())
            or sum(workers_by_lane.values()) > max_workers
        ):
            raise ValueError("lane_workers must include default and fit within max_workers")
        slots_by_lane = lane_in_flight or {"default": max_in_flight}
        if set(slots_by_lane) != set(workers_by_lane) or any(
            slots_by_lane[lane] < workers_by_lane[lane] for lane in workers_by_lane
        ) or sum(slots_by_lane.values()) > max_in_flight:
            raise ValueError("lane_in_flight must match lanes and fit within max_in_flight")
        self._executors = {
            lane: ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix=f"gateway-{lane}-io"
            )
            for lane, workers in workers_by_lane.items()
        }
        self._slots = {
            lane: asyncio.Semaphore(slots_by_lane[lane]) for lane in workers_by_lane
        }
        self._stats_lock = Lock()
        self._lane_stats = {
            lane: {
                "active_workers": 0,
                "in_flight": 0,
                "admission_wait_seconds_total": 0.0,
                "admission_rejects_total": 0,
                "worker_execution_seconds_total": 0.0,
                "worker_execution_seconds_max": 0.0,
                "operation_execution_seconds_max": {},
            }
            for lane in workers_by_lane
        }
        self._admission_timeout_seconds = admission_timeout_seconds
        self._dependency_recovery_seconds = dependency_recovery_seconds
        self._dependency_lock = Lock()
        self._dependency_open_until: dict[str, float] = {}
        self._dependency_probe_inflight: set[str] = set()
        self._closed = False

    async def run(
        self,
        function: Callable[..., T],
        /,
        *args: Any,
        dependency: str | None = None,
        probe: bool = False,
        recovery_probe: bool = False,
        **kwargs: Any,
    ) -> T:
        if self._closed:
            raise RuntimeError("blocking I/O executor is closed")
        if (probe or recovery_probe) and dependency is None:
            raise ValueError("probe calls must identify a dependency")
        if probe and recovery_probe:
            raise ValueError("a call cannot be both a readiness and recovery probe")
        lane = dependency if dependency in self._executors else "default"
        admission_started = monotonic()
        probe_permit = self._begin_call(dependency, probe, recovery_probe)
        try:
            await asyncio.wait_for(
                self._slots[lane].acquire(), timeout=self._admission_timeout_seconds
            )
        except TimeoutError as exc:
            with self._stats_lock:
                self._lane_stats[lane]["admission_rejects_total"] += 1
                self._lane_stats[lane]["admission_wait_seconds_total"] += (
                    monotonic() - admission_started
                )
            self._finish_probe(dependency, probe_permit)
            raise BlockingIOOverloadedError("blocking I/O lane is saturated") from exc
        except BaseException:
            self._finish_probe(dependency, probe_permit)
            raise

        loop = asyncio.get_running_loop()
        operation = self._operation_name(function)
        with self._stats_lock:
            self._lane_stats[lane]["in_flight"] += 1
            self._lane_stats[lane]["admission_wait_seconds_total"] += (
                monotonic() - admission_started
            )
        try:
            future = loop.run_in_executor(
                self._executors[lane],
                lambda: self._invoke(
                    function, args, kwargs, dependency, probe_permit, lane, operation
                ),
            )
            cancelled = False
            while True:
                try:
                    result = await asyncio.shield(future)
                    break
                except asyncio.CancelledError:
                    # The worker cannot be stopped. Drain it before propagating
                    # cancellation so callers never race cleanup against a DB
                    # commit whose result is still in flight.
                    cancelled = True
                    current = asyncio.current_task()
                    if current is not None:
                        current.uncancel()
                except BaseException as exc:
                    self._record_failure(dependency, exc)
                    raise
            if cancelled:
                raise asyncio.CancelledError
            return result
        finally:
            with self._stats_lock:
                self._lane_stats[lane]["in_flight"] -= 1
            self._slots[lane].release()
            self._finish_probe(dependency, probe_permit)

    def _begin_call(self, dependency: str | None, probe: bool, recovery_probe: bool) -> bool:
        if dependency is None:
            return False
        with self._dependency_lock:
            open_until = self._dependency_open_until.get(dependency, 0.0)
            if not open_until:
                return False
            if recovery_probe:
                if dependency in self._dependency_probe_inflight:
                    raise DependencyCircuitOpenError(
                        f"{dependency} recovery query already in flight"
                    )
                self._dependency_probe_inflight.add(dependency)
                return True
            if not probe:
                raise DependencyCircuitOpenError(f"{dependency} dependency circuit is open")
            if monotonic() < open_until or dependency in self._dependency_probe_inflight:
                raise DependencyCircuitOpenError(f"{dependency} dependency is recovering")
            self._dependency_probe_inflight.add(dependency)
            return True

    def _invoke(
        self,
        function: Callable[..., T],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        dependency: str | None,
        probe_permit: bool,
        lane: str,
        operation: str,
    ) -> T:
        # Work already queued when another call discovers an outage must not
        # start another connection attempt after its worker becomes available.
        if dependency is not None and not probe_permit:
            with self._dependency_lock:
                if dependency in self._dependency_open_until:
                    raise DependencyCircuitOpenError(
                        f"{dependency} dependency circuit is open"
                    )
        started = monotonic()
        with self._stats_lock:
            self._lane_stats[lane]["active_workers"] += 1
        try:
            return function(*args, **kwargs)
        except BaseException as exc:
            # Trip from the worker before it picks the next queued task. If we
            # wait for the asyncio callback, a sibling connection attempt can
            # start in the scheduling gap after this worker returns.
            self._record_failure(dependency, exc)
            raise
        finally:
            duration = monotonic() - started
            with self._stats_lock:
                stats = self._lane_stats[lane]
                stats["active_workers"] -= 1
                stats["worker_execution_seconds_total"] += duration
                stats["worker_execution_seconds_max"] = max(
                    stats["worker_execution_seconds_max"], duration
                )
                operation_max = stats["operation_execution_seconds_max"]
                operation_max[operation] = max(operation_max.get(operation, 0.0), duration)

    @staticmethod
    def _operation_name(function: Callable[..., Any]) -> str:
        name = getattr(function, "__qualname__", getattr(function, "__name__", "call"))
        return re.sub(r"[^a-zA-Z0-9_]", "_", name)[:80] or "call"

    def _record_failure(self, dependency: str | None, exc: BaseException) -> None:
        if dependency is None or not self._is_dependency_failure(exc):
            return
        with self._dependency_lock:
            self._dependency_open_until[dependency] = (
                monotonic() + self._dependency_recovery_seconds
            )

    @staticmethod
    def _is_dependency_failure(exc: BaseException) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
            return True
        if type(exc).__module__ == "sqlite3" and type(exc).__name__ == "OperationalError":
            return True
        return type(exc).__module__.startswith("psycopg") and any(
            base.__name__ in {"OperationalError", "InterfaceError"}
            for base in type(exc).__mro__
        )

    def _finish_probe(self, dependency: str | None, probe_permit: bool) -> None:
        if dependency is not None and probe_permit:
            with self._dependency_lock:
                self._dependency_probe_inflight.discard(dependency)

    def report_dependency_failure(self, dependency: str) -> None:
        """Open a circuit when a dependency probe reports unhealthy without raising."""
        with self._dependency_lock:
            self._dependency_open_until[dependency] = (
                monotonic() + self._dependency_recovery_seconds
            )
            self._dependency_probe_inflight.discard(dependency)

    def dependency_circuit_open(self, dependency: str) -> bool:
        """Return whether traffic is currently rejected by this dependency circuit."""
        with self._dependency_lock:
            return self._dependency_open_until.get(dependency, 0.0) > monotonic()

    def report_dependency_success(self, dependency: str) -> None:
        """Close a dependency circuit only after an explicit healthy probe."""
        with self._dependency_lock:
            self._dependency_open_until.pop(dependency, None)
            self._dependency_probe_inflight.discard(dependency)

    def snapshot(self) -> dict[str, Any]:
        """Return bounded executor and dependency-circuit diagnostics."""
        with self._stats_lock:
            lanes = {
                name: {
                    **stats,
                    "queued_operations": max(
                        0, stats["in_flight"] - stats["active_workers"]
                    ),
                }
                for name, stats in self._lane_stats.items()
            }
        now = monotonic()
        with self._dependency_lock:
            circuits = {
                dependency: {
                    "open": until > now,
                    "recovery_probe_inflight": dependency
                    in self._dependency_probe_inflight,
                }
                for dependency, until in self._dependency_open_until.items()
            }
        return {"lanes": lanes, "circuits": circuits}

    def prometheus(self, prefix: str = "llm_gateway") -> str:
        """Render low-cardinality executor diagnostics in Prometheus text format."""
        snapshot = self.snapshot()
        lines: list[str] = []
        fields = (
            "active_workers",
            "queued_operations",
            "in_flight",
            "admission_wait_seconds_total",
            "admission_rejects_total",
            "worker_execution_seconds_total",
            "worker_execution_seconds_max",
        )
        for field in fields:
            metric = f"{prefix}_blocking_io_{field}"
            metric_type = "counter" if field.endswith("_total") else "gauge"
            lines.extend((f"# TYPE {metric} {metric_type}",))
            for lane, values in snapshot["lanes"].items():
                value = values[field]
                lines.append(f'{metric}{{lane="{lane}"}} {value:.6g}')
        metric = f"{prefix}_blocking_io_operation_execution_seconds_max"
        lines.append(f"# TYPE {metric} gauge")
        for lane, values in snapshot["lanes"].items():
            for operation, duration in values["operation_execution_seconds_max"].items():
                lines.append(
                    f'{metric}{{lane="{lane}",operation="{operation}"}} {duration:.6g}'
                )
        metric = f"{prefix}_dependency_circuit_open"
        lines.append(f"# TYPE {metric} gauge")
        for dependency, value in snapshot["circuits"].items():
            lines.append(
                f'{metric}{{dependency="{dependency}"}} {int(value["open"])}'
            )
        return "\n".join(lines) + "\n"

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.gather(
            *(
                asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=False)
                for executor in self._executors.values()
            )
        )
