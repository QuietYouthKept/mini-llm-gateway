"""Bounded dependency checks used by the traffic readiness endpoint.

Readiness is deliberately separate from liveness: a process can respond to an
HTTP request while it is unable to enforce the shared budget or rate limit.
The checks here never include credentials, connection strings, or provider
responses in their output.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from app.application.services.blocking_io import DependencyCircuitOpenError
from app.application.services.circuit_breaker import CircuitState
from app.infrastructure.persistence.sqlite.connection import schema_checksum
from app.infrastructure.persistence.sqlite.schema import SCHEMA_VERSION

if TYPE_CHECKING:
    from app.core.container import AppContainer


@dataclass
class DependencyStatus:
    name: str
    required: bool
    healthy: bool
    state: str
    last_success_at: float | None = None
    detail: str | None = None

    def public(self) -> dict[str, Any]:
        return asdict(self)


class ReadinessService:
    """Cache dependency state and require a small recovery window.

    A failure removes a node immediately. Two consecutive healthy probes are
    required before it rejoins, preventing flapping dependencies from
    repeatedly receiving traffic. Checks run under a per-check deadline so a
    probe storm cannot amplify an outage.
    """

    def __init__(self, *, timeout_seconds: float = 0.8, recovery_successes: int = 2) -> None:
        self._timeout_seconds = timeout_seconds
        self._recovery_successes = max(1, recovery_successes)
        self._successes: dict[str, int] = {}
        self._last_success: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def assess(self, container: AppContainer) -> dict[str, DependencyStatus]:
        checks: list[tuple[str, bool, Any]] = [
            ("database", True, lambda: self._database_check(container.db_path)),
        ]
        if container.redis_url:
            checks.append(("redis_rate_limit", True, lambda: self._redis_check(container)))
            checks.append(("redis_cache", False, lambda: self._redis_cache_check(container)))
        checks.append(("providers", True, lambda: self._providers_check(container)))
        results = await asyncio.gather(
            *(
                self._run_check(name, required, check, getattr(container, "blocking_io", None))
                for name, required, check in checks
            )
        )
        return {result.name: result for result in results}

    async def _run_check(
        self, name: str, required: bool, check: Any, blocking_io: Any
    ) -> DependencyStatus:
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            dependency_failed = False
            try:
                # The shared bounded executor prevents readiness probes from
                # creating detached default-executor threads during outages.
                if blocking_io is None:
                    healthy, detail = await asyncio.to_thread(check)
                elif name == "database":
                    healthy, detail = await blocking_io.run(
                        check, dependency="database", probe=True
                    )
                else:
                    healthy, detail = await blocking_io.run(check)
            except TimeoutError:
                healthy, detail = False, "timeout"
                dependency_failed = True
            except DependencyCircuitOpenError:
                healthy, detail = False, "circuit_open"
            except Exception:
                healthy, detail = False, "unavailable"
                dependency_failed = True
            if name == "database" and blocking_io is not None:
                if healthy:
                    blocking_io.report_dependency_success("database")
                elif dependency_failed or detail != "circuit_open":
                    blocking_io.report_dependency_failure("database")
        async with lock:
            now = time.time()
            if healthy:
                count = self._successes.get(name, 0) + 1
                self._successes[name] = count
                self._last_success[name] = now
                recovered = count >= self._recovery_successes
                return DependencyStatus(
                    name=name,
                    required=required,
                    healthy=recovered,
                    state="healthy" if recovered else "recovering",
                    last_success_at=now,
                    detail=detail,
                )
            self._successes[name] = 0
            return DependencyStatus(
                name=name,
                required=required,
                healthy=False,
                state="unhealthy",
                last_success_at=self._last_success.get(name),
                detail=detail,
            )

    @staticmethod
    def _database_check(db_path: str) -> tuple[bool, str]:
        if db_path.startswith(("postgresql://", "postgres://")):
            from app.infrastructure.persistence.postgresql.connection import schema_is_current

            return (
                schema_is_current(
                    db_path,
                    connect_timeout=1,
                    statement_timeout_ms=500,
                    lock_timeout_ms=500,
                ),
                "postgresql",
            )
        connection = sqlite3.connect(db_path, timeout=0.5)
        try:
            row = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version = ?", (SCHEMA_VERSION,)
            ).fetchone()
            return bool(row and row[0] == schema_checksum()), "sqlite"
        finally:
            connection.close()

    @staticmethod
    def _redis_check(container: AppContainer) -> tuple[bool, str]:
        checker = getattr(container.rate_limiter, "healthcheck", None)
        return bool(checker and checker()), "redis"

    @staticmethod
    def _redis_cache_check(container: AppContainer) -> tuple[bool, str]:
        checker = getattr(container.prompt_cache, "healthcheck", None)
        return (True, "not_configured") if checker is None else (bool(checker()), "redis")

    @staticmethod
    def _providers_check(container: AppContainer) -> tuple[bool, str]:
        usable = 0
        for provider_id, provider in container.providers.items():
            config = container.config.providers[provider_id]
            if not config.enabled:
                continue
            if config.type == "openai_compatible":
                has_secret = bool(config.http.api_key) or bool(
                    config.http.api_key_env and os.getenv(config.http.api_key_env)
                )
                if not has_secret:
                    continue
            breaker = container.circuit_breakers.get(provider_id)
            if breaker is not None and breaker.state == CircuitState.OPEN:
                continue
            if provider is not None:
                usable += 1
        return usable > 0, f"usable={usable}"
