"""mock_stable — reliable, slightly slower mock provider."""

from __future__ import annotations

from app.domain.models.provider import ProviderBehavior, ProviderType
from app.infrastructure.providers.base import BaseMockProvider


class MockStableProvider(BaseMockProvider):
    def __init__(self, behavior: ProviderBehavior | None = None) -> None:
        super().__init__(
            provider_id="mock_stable",
            provider_type=ProviderType.MOCK.value,
            behavior=behavior or ProviderBehavior(
                latency_ms=180,
                error_rate=0.0,
                timeout_ms=1000,
                default_response="stable response from mock_stable",
            ),
        )
