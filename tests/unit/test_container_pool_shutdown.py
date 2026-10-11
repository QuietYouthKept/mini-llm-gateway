from __future__ import annotations

from app.core.container import AppContainer
from app.infrastructure.persistence.postgresql import connection


async def test_container_shutdown_drains_readiness_and_db_lanes_before_pool(monkeypatch) -> None:
    events: list[str] = []

    class AsyncCloser:
        def __init__(self, name: str) -> None:
            self.name = name

        async def aclose(self) -> None:
            events.append(self.name)

    container = object.__new__(AppContainer)
    container.db_path = "postgresql://gateway:synthetic@127.0.0.1/gateway"
    container.providers = {}
    container.rate_limiter = None
    container.prompt_cache = None
    container.distributed_singleflight = None
    container.tracer = None
    container.readiness = AsyncCloser("readiness")
    container.blocking_io = AsyncCloser("blocking_io")

    def close_pool(database_url: str) -> None:
        assert database_url == container.db_path
        events.append("pool")

    monkeypatch.setattr(connection, "close_pool", close_pool)

    await container.close()

    assert events == ["readiness", "blocking_io", "pool"]
