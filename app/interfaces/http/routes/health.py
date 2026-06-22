from __future__ import annotations

from fastapi import APIRouter

from app.interfaces.http.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", service="mini-llm-gateway")
