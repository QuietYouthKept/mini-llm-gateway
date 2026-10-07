from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.main import app, create_app


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "mini-llm-gateway"


def test_readiness_requires_recovery_window_and_liveness_stays_available(container) -> None:  # noqa: ANN001
    with TestClient(create_app(container)) as test_client:
        assert test_client.get("/live").status_code == 200
        first = test_client.get("/ready")
        second = test_client.get("/ready")
    assert first.status_code == 503
    assert first.json()["dependencies"]["database"]["state"] == "recovering"
    assert second.status_code == 200
    assert second.json()["dependencies"]["database"]["state"] == "healthy"


def test_dependency_status_is_admin_only_and_safe(container) -> None:  # noqa: ANN001
    with TestClient(create_app(container)) as test_client:
        assert test_client.get("/health/dependencies").status_code == 401
        response = test_client.get("/health/dependencies", headers={"x-admin-key": "admin-key"})
    assert response.status_code == 200
    assert "redis://" not in response.text
    assert "admin-key" not in response.text
