"""Request audit-trail endpoint."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.container import AppContainer
from app.domain.errors import RequestNotFoundError
from app.infrastructure.config.config_models import ClientConfig
from app.interfaces.http.dependencies.auth import require_api_key
from app.interfaces.http.dependencies.container import get_container

router = APIRouter(prefix="/v1", tags=["requests"])


@router.get("/requests/{request_id}")
async def get_request(
    request_id: str,
    client: Annotated[ClientConfig, Depends(require_api_key)],
    container: Annotated[AppContainer, Depends(get_container)],
) -> dict:
    if container.blocking_io is None:
        data = await asyncio.to_thread(container.log_service.get, request_id)
    else:
        data = await container.blocking_io.run(container.log_service.get, request_id)
    if data is None or data.get("client_id") != client.client_id:
        raise RequestNotFoundError(request_id)
    return data
