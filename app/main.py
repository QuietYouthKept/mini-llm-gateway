from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.core.container import AppContainer
from app.core.startup import bootstrap
from app.domain.errors import GatewayError
from app.interfaces.http.exception_handlers import (
    gateway_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.interfaces.http.middleware import HttpAuditMiddleware, RequestContextMiddleware
from app.interfaces.http.routes import admin, chat, health, metrics, requests


def create_app(container: AppContainer | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container if container is not None else bootstrap()
        app.state.retired_containers = []
        metrics = app.state.container.gateway_metrics

        async def observe_event_loop() -> None:
            loop = asyncio.get_running_loop()
            interval = 0.1
            expected = loop.time() + interval
            while True:
                await asyncio.sleep(max(0.0, expected - loop.time()))
                now = loop.time()
                metrics.event_loop_lag.set(max(0.0, now - expected))
                metrics.event_loop_tasks.set(float(len(asyncio.all_tasks())))
                expected = now + interval

        loop_monitor = asyncio.create_task(observe_event_loop(), name="gateway-loop-metrics")
        try:
            yield
        finally:
            loop_monitor.cancel()
            await asyncio.gather(loop_monitor, return_exceptions=True)
            closed: set[int] = set()
            await app.state.container.close(closed)
            for retired in app.state.retired_containers:
                await retired.close(closed)

    app = FastAPI(
        title="mini-llm-gateway",
        version="1.0.0rc1",
        lifespan=lifespan,
    )

    # Last added is outermost: request context must wrap HTTP audit.
    app.add_middleware(HttpAuditMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(GatewayError, gateway_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(requests.router)
    app.include_router(metrics.router)
    app.include_router(admin.router)
    return app


app = create_app()
