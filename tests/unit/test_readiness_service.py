from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.application.services.blocking_io import BoundedBlockingIO
from app.application.services.readiness_service import ReadinessService
from app.infrastructure.persistence.sqlite.connection import init_db


class HealthyDependency:
    def healthcheck(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_redis_dependencies_are_checked_as_callables(tmp_path) -> None:
    database = str(tmp_path / "readiness.db")
    init_db(database)
    container = SimpleNamespace(
        db_path=database,
        redis_url="redis://redis.test:6379/0",
        rate_limiter=HealthyDependency(),
        prompt_cache=HealthyDependency(),
        providers={},
        config=SimpleNamespace(providers={}),
    )

    statuses = await ReadinessService(recovery_successes=1).assess(container)

    assert statuses["redis_rate_limit"].healthy is True
    assert statuses["redis_rate_limit"].detail == "redis"
    assert statuses["redis_cache"].healthy is True
    assert statuses["redis_cache"].detail == "redis"


@pytest.mark.asyncio
async def test_database_readiness_fails_fast_then_uses_recovery_probe(
    container, monkeypatch
) -> None:  # noqa: ANN001
    io = BoundedBlockingIO(dependency_recovery_seconds=0.02)
    container.blocking_io = io
    container.db_path = "postgresql://not-used-by-patched-check"
    container.readiness = ReadinessService(recovery_successes=2)
    healthy = False
    probe_count = 0

    def database_check(_db_path: str) -> tuple[bool, str]:
        nonlocal probe_count
        probe_count += 1
        return healthy, "postgresql"

    monkeypatch.setattr(
        ReadinessService, "_database_check", staticmethod(database_check)
    )
    try:
        down = await container.readiness.assess(container)
        assert down["database"].healthy is False
        assert down["database"].state == "unhealthy"

        fast_failed = await container.readiness.assess(container)
        assert fast_failed["database"].detail == "circuit_open"
        assert probe_count == 1

        await asyncio.sleep(0.03)
        healthy = True
        recovering = await container.readiness.assess(container)
        assert recovering["database"].healthy is False
        assert recovering["database"].state == "recovering"
        ready = await container.readiness.assess(container)
        assert ready["database"].healthy is True
        assert ready["database"].state == "healthy"
    finally:
        await io.aclose()
