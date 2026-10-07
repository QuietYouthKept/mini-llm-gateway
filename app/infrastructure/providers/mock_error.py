"""mock_error — mock provider that always returns an error."""

from __future__ import annotations

from app.domain.models.provider import ProviderBehavior, ProviderType
from app.infrastructure.providers.base import BaseMockProvider


class MockErrorProvider(BaseMockProvider):
    def __init__(self, behavior: ProviderBehavior | None = None) -> None:
        super().__init__(
            provider_id="mock_error",
            provider_type=ProviderType.MOCK.value,
            behavior=behavior
            or ProviderBehavior(
                latency_ms=50,
                error_rate=1.0,
                timeout_ms=1000,
                default_response="this should usually fail",
            ),
        )
