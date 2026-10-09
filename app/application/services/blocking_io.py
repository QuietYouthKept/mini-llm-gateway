"""Bounded bridge for synchronous database and Redis clients.

Repository ports are intentionally synchronous today.  Async request handlers
must route those calls through this adapter so an outage cannot pin the ASGI
event loop.  Cancellation is deferred until an already-running operation has
finished: Python cannot stop a worker thread, and returning early from a write
could otherwise make its commit outcome appear known when it is not.
"""

from __future__ import annotations

import asyncio
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
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="gateway-blocking-io"
        )
        self._slots = asyncio.Semaphore(max_in_flight)
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
        probe_permit = self._begin_call(dependency, probe, recovery_probe)
        try:
            await asyncio.wait_for(
                self._slots.acquire(), timeout=self._admission_timeout_seconds
            )
        except TimeoutError as exc:
            self._finish_probe(dependency, probe_permit)
            raise BlockingIOOverloadedError("blocking I/O lane is saturated") from exc
        except BaseException:
            self._finish_probe(dependency, probe_permit)
            raise

        loop = asyncio.get_running_loop()
        try:
            future = loop.run_in_executor(
                self._executor,
                lambda: self._invoke(function, args, kwargs, dependency, probe_permit),
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
            self._slots.release()
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
    ) -> T:
        # Work already queued when another call discovers an outage must not
        # start another connection attempt after its worker becomes available.
        if dependency is not None and not probe_permit:
            with self._dependency_lock:
                if dependency in self._dependency_open_until:
                    raise DependencyCircuitOpenError(
                        f"{dependency} dependency circuit is open"
                    )
        try:
            return function(*args, **kwargs)
        except BaseException as exc:
            # Trip from the worker before it picks the next queued task. If we
            # wait for the asyncio callback, a sibling connection attempt can
            # start in the scheduling gap after this worker returns.
            self._record_failure(dependency, exc)
            raise

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

    def report_dependency_success(self, dependency: str) -> None:
        """Close a dependency circuit only after an explicit healthy probe."""
        with self._dependency_lock:
            self._dependency_open_until.pop(dependency, None)
            self._dependency_probe_inflight.discard(dependency)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=False)
