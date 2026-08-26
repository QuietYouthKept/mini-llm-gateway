"""Per-provider circuit breaker (closed / open / half-open)."""

from __future__ import annotations

import threading
import time
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """A simple stateful circuit breaker.

    - closed: requests flow normally; consecutive failures are counted.
    - open: requests are rejected without calling the provider; after the
      recovery timeout the breaker transitions to half-open.
    - half_open: a limited number of probe requests are allowed through; a
      success closes the breaker, a failure re-opens it.
    """

    def __init__(
        self,
        provider_id: str,
        failure_threshold: int = 3,
        recovery_timeout_ms: int = 5000,
        half_open_max_calls: int = 1,
    ) -> None:
        self.provider_id = provider_id
        self._failure_threshold = max(1, failure_threshold)
        self._recovery_timeout_ms = recovery_timeout_ms
        self._half_open_max_calls = max(1, half_open_max_calls)

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition()
            return self._state

    def allow_request(self) -> bool:
        """Return True if a request may be sent to the provider right now."""
        with self._lock:
            self._maybe_transition()
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                return False
            # HALF_OPEN
            if self._half_open_in_flight >= self._half_open_max_calls:
                return False
            self._half_open_in_flight += 1
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
                self._open()
                return
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._open()

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()

    def _maybe_transition(self) -> None:
        if self._state != CircuitState.OPEN or self._opened_at is None:
            return
        elapsed_ms = (time.monotonic() - self._opened_at) * 1000
        if elapsed_ms >= self._recovery_timeout_ms:
            self._state = CircuitState.HALF_OPEN
            self._half_open_in_flight = 0
