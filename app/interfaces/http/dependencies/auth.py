"""API key authentication and admin authentication dependencies."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Annotated

from fastapi import Depends, Request

from app.core.container import AppContainer
from app.core.request_context import get_request_id
from app.domain.errors import AuthFailedError
from app.infrastructure.config.config_models import ClientConfig
from app.interfaces.http.dependencies.container import get_container


def _extract_key(request: Request) -> str:
    authorization_values = request.headers.getlist("Authorization")
    api_key_values = request.headers.getlist("x-api-key")
    if len(authorization_values) > 1 or len(api_key_values) > 1:
        return ""
    auth = authorization_values[0] if authorization_values else ""
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :].strip()
    return api_key_values[0].strip() if api_key_values else ""


def _lookup_client(container: AppContainer, api_key: str) -> ClientConfig | None:
    candidate = hashlib.sha256(api_key.encode()).hexdigest()
    # Compare every configured digest so an authentication failure does not
    # reveal which key ID exists through a fast dictionary miss.
    matched: ClientConfig | None = None
    for digest, client in container.clients_by_key.items():
        if hmac.compare_digest(candidate, digest):
            matched = client
    return matched


async def require_api_key(
    request: Request,
    container: Annotated[AppContainer, Depends(get_container)],
) -> ClientConfig:
    started = time.monotonic()
    try:
        with container.tracer.span("auth.duration"):
            api_key = _extract_key(request)
            client = _lookup_client(container, api_key) if api_key else None
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
    values = request.headers.getlist("x-admin-key")
    provided = values[0].strip() if len(values) == 1 else ""
    expected = container.config.admin.api_key or os.getenv(container.config.admin.api_key_env, "")
    if not expected or not hmac.compare_digest(provided, expected):
        raise AuthFailedError(message="Invalid admin key", request_id=get_request_id())
