"""mock_fast — fast, reliable mock provider."""

from __future__ import annotations

from app.domain.models.provider import ProviderBehavior, ProviderType
from app.infrastructure.providers.base import BaseMockProvider


class MockFastProvider(BaseMockProvider):
    def __init__(self, behavior: ProviderBehavior | None = None) -> None:
        super().__init__(
            provider_id="mock_fast",
            provider_type=ProviderType.MOCK.value,
            behavior=behavior or ProviderBehavior(
                latency_ms=80,
                error_rate=0.0,
                timeout_ms=1000,
                default_response="fast response from mock_fast",
            ),
        )
