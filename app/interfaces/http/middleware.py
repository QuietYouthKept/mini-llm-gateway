"""Request context middleware — propagates a request_id across the request."""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid
from typing import Any

from starlette.responses import JSONResponse

from app.core.request_context import get_request_id, request_id_var

logger = logging.getLogger(__name__)


class RequestContextMiddleware:
    """Pure ASGI middleware so contextvars propagate reliably into handlers."""

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = ""
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                request_id = value.decode("latin-1")
                break
        if not request_id:
            request_id = uuid.uuid4().hex

        token = request_id_var.set(request_id)
        status_code = 500

        app = scope.get("app")
        container = getattr(getattr(app, "state", None), "container", None)
        tracer = getattr(container, "tracer", None)
        path = scope.get("path", "")
        route = (
            path
            if path in {"/live", "/ready", "/metrics", "/v1/chat", "/v1/chat/completions"}
            else "/v1/requests/{request_id}"
            if path.startswith("/v1/requests/")
            else "unmatched"
        )
        trace = (
            tracer.span(
                "http.server.request",
                {
                    "request.id": request_id,
                    "http.request.method": scope.get("method", ""),
                    "http.route": route,
                },
            )
            if tracer is not None
            else None
        )

        async def send_wrapper(message) -> None:  # noqa: ANN001
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        try:
            if trace is None:
                await self._dispatch(scope, receive, send_wrapper)
            else:
                with trace as span:
                    try:
                        await self._dispatch(scope, receive, send_wrapper)
                    finally:
                        span.attributes["http.response.status_code"] = status_code
        finally:
            request_id_var.reset(token)

    async def _dispatch(self, scope, receive, send_wrapper) -> None:  # noqa: ANN001
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            frames = traceback.extract_tb(exc.__traceback__)
            logger.error(
                "Unhandled HTTP exception class=%s.%s request_id=%s stack=%s",
                type(exc).__module__,
                type(exc).__name__,
                get_request_id(),
                " <- ".join(
                    f"{frame.filename.rsplit('/', 1)[-1]}:{frame.name}:{frame.lineno}"
                    for frame in frames[-8:]
                ),
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "message": "Internal server error",
                        "type": "internal_error",
                        "code": "internal_error",
                        "request_id": get_request_id(),
                    }
                },
            )
            await response(scope, receive, send_wrapper)


class HttpAuditMiddleware:
    """Audit HTTP failures that occur before or outside ChatService."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code = 500
        start = time.monotonic()
        response_started_at: float | None = None
        response_completed_at: float | None = None
        cancelled = False

        async def send_wrapper(message) -> None:  # noqa: ANN001
            nonlocal status_code, response_started_at, response_completed_at
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                response_started_at = time.monotonic()
            await send(message)
            if (
                message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                response_completed_at = time.monotonic()

        try:
            await self.app(scope, receive, send_wrapper)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            app = scope.get("app")
            container = getattr(getattr(app, "state", None), "container", None)
            if container is not None and response_started_at is not None:
                route = scope.get("route")
                endpoint = getattr(route, "path", None) or scope.get("path", "")
                if endpoint not in {
                    "/live",
                    "/health",
                    "/ready",
                    "/health/dependencies",
                    "/metrics",
                    "/v1/chat",
                    "/v1/chat/completions",
                    "/v1/requests/{request_id}",
                    "/admin/config",
                    "/admin/reload-config",
                    "/admin/reconcile-budget-reservations",
                }:
                    endpoint = "other"
                completed = response_completed_at or time.monotonic()
                container.gateway_metrics.record_http_response(
                    endpoint,
                    status_code,
                    response_started_at - start,
                    completed - start,
                )
            if (
                status_code >= 400
                and not cancelled
                and not scope.get("gateway.audit_skipped")
            ):
                await self._record_if_missing(scope, status_code, start)

    @staticmethod
    async def _record_if_missing(
        scope: dict[str, Any], status_code: int, start: float
    ) -> None:
        app = scope.get("app")
        container = getattr(getattr(app, "state", None), "container", None)
        if container is None:
            return
        request_id = get_request_id()
        try:
            if container.blocking_io is None:
                existing = await asyncio.to_thread(container.log_service.get, request_id)
            else:
                existing = await container.blocking_io.run(
                    container.log_service.get, request_id, dependency="database"
                )
            if existing is not None:
                return
            headers = {name.lower(): value for name, value in scope.get("headers", [])}
            auth = headers.get(b"authorization", b"").decode("latin-1")
            key = auth[7:].strip() if auth.startswith("Bearer ") else ""
            if not key:
                key = headers.get(b"x-api-key", b"").decode("latin-1").strip()
            client = container.clients_by_key.get(key)
            error_code = {
                401: "auth_failed",
                404: "http_not_found",
                422: "validation_error",
            }.get(status_code, "internal_error" if status_code >= 500 else "http_error")
            duration_ms = int((time.monotonic() - start) * 1000)
            record = container.log_service.record_error
            if container.blocking_io is None:
                await asyncio.to_thread(
                    record,
                    request_id=request_id,
                    client_id=client.client_id if client else "",
                    model_profile=None,
                    endpoint=scope.get("path", ""),
                    status_code=status_code,
                    error_code=error_code,
                    error_message=f"HTTP {status_code}",
                    duration_ms=duration_ms,
                )
            else:
                await container.blocking_io.run(
                    record,
                    request_id=request_id,
                    client_id=client.client_id if client else "",
                    model_profile=None,
                    endpoint=scope.get("path", ""),
                    status_code=status_code,
                    error_code=error_code,
                    error_message=f"HTTP {status_code}",
                    duration_ms=duration_ms,
                    dependency="database",
                )
            container.gateway_metrics.record_request(
                scope.get("path", ""), error_code, duration_ms / 1000.0
            )
        except Exception:
            container.gateway_metrics.audit_failures.inc()
