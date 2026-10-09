from __future__ import annotations

from types import SimpleNamespace

import pytest

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
