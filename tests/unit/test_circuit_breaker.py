"""Tests for the circuit breaker state machine."""

from __future__ import annotations

import time

from app.application.services.circuit_breaker import CircuitBreaker, CircuitState


def test_starts_closed_and_allows() -> None:
    cb = CircuitBreaker("p", failure_threshold=2)
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True


def test_opens_after_threshold_failures() -> None:
    cb = CircuitBreaker("p", failure_threshold=2)
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


def test_success_resets_failure_count() -> None:
    cb = CircuitBreaker("p", failure_threshold=2)
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED


def test_half_open_recovery() -> None:
    cb = CircuitBreaker("p", failure_threshold=1, recovery_timeout_ms=10)
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    time.sleep(0.03)
    assert cb.allow_request() is True  # transitions to half-open, allows probe
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_half_open_failure_reopens() -> None:
    cb = CircuitBreaker("p", failure_threshold=1, recovery_timeout_ms=10)
    cb.record_failure()
    time.sleep(0.03)
    assert cb.allow_request() is True
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
