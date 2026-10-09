"""Admin endpoints: config inspection and hot reload."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.core.container import AppContainer
from app.core.startup import bootstrap
from app.infrastructure.config.config_models import AppConfig
from app.interfaces.http.dependencies.auth import require_admin
from app.interfaces.http.dependencies.container import get_container

router = APIRouter(prefix="/admin", tags=["admin"])


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, val in value.items():
            if key in {"api_key", "api_key_hash", "api_key_env", "x-admin-key"}:
                redacted[key] = "***" if val else ""
            else:
                redacted[key] = _redact(val)
        return redacted
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _config_summary(config: AppConfig) -> dict[str, Any]:
    return _redact(asdict(config))


@router.get("/config")
async def get_config(
    container: Annotated[AppContainer, Depends(get_container)],
    _: Annotated[None, Depends(require_admin)],
) -> dict[str, Any]:
    return _config_summary(container.config)


@router.post("/reload-config")
async def reload_config(
    request: Request,
    container: Annotated[AppContainer, Depends(get_container)],
    _: Annotated[None, Depends(require_admin)],
) -> dict[str, Any]:
    new_container = await container.blocking_io.run(
        bootstrap,
        database_path=container.db_path,
        runtime_from=container,
        dependency="database",
    )
    request.app.state.container = new_container
    # Requests already in flight may still own old provider transports.  Retire
    # the old container at process shutdown instead of closing clients under them.
    request.app.state.retired_containers.append(container)
    await new_container.blocking_io.run(
        new_container.config_events.record,
        "reload",
        "config reloaded",
        dependency="database",
    )
    return {
        "status": "reloaded",
        "providers": len(new_container.providers),
        "profiles": len(new_container.profiles),
        "clients": len(new_container.clients_by_id),
    }


@router.post("/reconcile-budget-reservations")
async def reconcile_budget_reservations(
    container: Annotated[AppContainer, Depends(get_container)],
    _: Annotated[None, Depends(require_admin)],
) -> dict[str, int]:
    """Explicit maintenance action; never scan reservations on a chat request."""
    reclaimed = await container.blocking_io.run(
        container.budget_service.reconcile_expired_reservations,
        dependency="database",
    )
    if reclaimed:
        container.gateway_metrics.budget_reservation_leaks.inc(reclaimed)
    return {"reclaimed": reclaimed}
