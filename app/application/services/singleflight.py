"""Per-process request coalescing for identical cache misses."""

from __future__ import annotations

import asyncio
import threading


class SingleFlight:
    """Let one coroutine own a key while peers wait for its cache publication.

    This is intentionally process-local. Distributed coalescing belongs in a
    shared cache backend and is not implied by this class.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flights: dict[str, asyncio.Event] = {}

    def acquire(self, key: str) -> tuple[bool, asyncio.Event]:
        with self._lock:
            existing = self._flights.get(key)
            if existing is not None:
                return False, existing
            event = asyncio.Event()
            self._flights[key] = event
            return True, event

    def release(self, key: str, event: asyncio.Event) -> None:
        with self._lock:
            current = self._flights.get(key)
            if current is event:
                self._flights.pop(key, None)
                event.set()
