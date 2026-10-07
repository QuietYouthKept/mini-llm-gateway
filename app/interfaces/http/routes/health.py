from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.application.services.readiness_service import ReadinessService
from app.core.container import AppContainer
from app.interfaces.http.dependencies.auth import require_admin
from app.interfaces.http.dependencies.container import get_container
from app.interfaces.http.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def live_check() -> HealthResponse:
    """Process liveness only; it intentionally never calls a dependency."""
    return HealthResponse(status="ok", service="mini-llm-gateway")


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Backward-compatible alias for process liveness."""
    return await live_check()


async def _readiness(container: AppContainer) -> tuple[bool, dict[str, Any]]:
    if container.readiness is None:  # defensive for hand-built test containers
        container.readiness = ReadinessService()
    dependencies = await container.readiness.assess(container)
    public = {name: value.public() for name, value in dependencies.items()}
    ready = all(value.healthy for value in dependencies.values() if value.required)
    return ready, public


@router.get("/ready")
async def ready_check(
    container: Annotated[AppContainer, Depends(get_container)],
) -> JSONResponse:
    ready, dependencies = await _readiness(container)
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "service": "mini-llm-gateway",
            "dependencies": dependencies,
        },
    )


@router.get("/health/dependencies")
async def dependency_health(
    container: Annotated[AppContainer, Depends(get_container)],
    _: Annotated[None, Depends(require_admin)],
) -> dict[str, Any]:
    """Operator-only dependency state; fields are deliberately secret-free."""
    ready, dependencies = await _readiness(container)
    return {"status": "ready" if ready else "not_ready", "dependencies": dependencies}
