"""API key authentication and admin authentication dependencies."""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, Request

from app.core.container import AppContainer
from app.core.request_context import get_request_id
from app.domain.errors import AuthFailedError
from app.infrastructure.config.config_models import ClientConfig
from app.interfaces.http.dependencies.container import get_container


def _extract_key(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()
    return request.headers.get("x-api-key", "").strip()


async def require_api_key(
    request: Request,
    container: Annotated[AppContainer, Depends(get_container)],
) -> ClientConfig:
    started = time.monotonic()
    try:
        with container.tracer.span("auth.duration"):
            api_key = _extract_key(request)
            client = container.clients_by_key.get(api_key) if api_key else None
            if client is None:
                container.gateway_metrics.auth_failed.inc()
                raise AuthFailedError(request_id=get_request_id())
            return client
    finally:
        container.gateway_metrics.record_phase("auth.duration", time.monotonic() - started)


async def require_admin(
    request: Request,
    container: Annotated[AppContainer, Depends(get_container)],
) -> None:
    if not container.config.admin.enabled:
        raise AuthFailedError(message="Admin API is disabled", request_id=get_request_id())
    provided = request.headers.get("x-admin-key", "").strip()
    if provided != container.config.admin.api_key:
        raise AuthFailedError(message="Invalid admin key", request_id=get_request_id())
