"""Prometheus metrics endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.container import AppContainer
from app.interfaces.http.dependencies.container import get_container

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def metrics(
    container: Annotated[AppContainer, Depends(get_container)],
) -> Response:
    if not container.config.metrics.enabled:
        raise HTTPException(status_code=404, detail="metrics disabled")
    container.chat_service.sync_circuit_metrics()
    return Response(
        content=container.metrics_registry.render(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
