"""mock_slow — slow mock provider that exceeds typical timeouts."""

from __future__ import annotations

from app.domain.models.provider import ProviderBehavior, ProviderType
from app.infrastructure.providers.base import BaseMockProvider


class MockSlowProvider(BaseMockProvider):
    def __init__(self, behavior: ProviderBehavior | None = None) -> None:
        super().__init__(
            provider_id="mock_slow",
            provider_type=ProviderType.MOCK.value,
            behavior=behavior or ProviderBehavior(
                latency_ms=2000,
                error_rate=0.0,
                timeout_ms=1000,
                default_response="slow response from mock_slow",
            ),
        )

    def _should_timeout(self) -> bool:
        # mock_slow always exceeds its timeout
        return True
