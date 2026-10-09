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
from typing import Any, TypeVar

T = TypeVar("T")


class BlockingIOOverloadedError(RuntimeError):
    """Raised when the bounded synchronous-I/O lane cannot admit more work."""


class BoundedBlockingIO:
    def __init__(
        self,
        *,
        max_workers: int = 8,
        max_in_flight: int = 16,
        admission_timeout_seconds: float = 0.25,
    ) -> None:
        if max_workers < 1 or max_in_flight < max_workers:
            raise ValueError("max_in_flight must be at least one and no less than max_workers")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="gateway-blocking-io"
        )
        self._slots = asyncio.Semaphore(max_in_flight)
        self._admission_timeout_seconds = admission_timeout_seconds
        self._closed = False

    async def run(self, function: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
        if self._closed:
            raise RuntimeError("blocking I/O executor is closed")
        try:
            await asyncio.wait_for(
                self._slots.acquire(), timeout=self._admission_timeout_seconds
            )
        except TimeoutError as exc:
            raise BlockingIOOverloadedError("blocking I/O lane is saturated") from exc

        loop = asyncio.get_running_loop()
        try:
            future = loop.run_in_executor(
                self._executor, lambda: function(*args, **kwargs)
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
            if cancelled:
                raise asyncio.CancelledError
            return result
        finally:
            self._slots.release()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=False)
