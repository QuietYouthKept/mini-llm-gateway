"""Provider registry — maps provider IDs to ProviderPort implementations."""

from __future__ import annotations

from app.domain.models.provider import ProviderBehavior, ProviderType
from app.domain.ports.provider_port import ProviderPort
from app.infrastructure.config.config_models import ProviderConfig
from app.infrastructure.providers.base import BaseMockProvider
from app.infrastructure.providers.fake_static import FakeStaticProvider
from app.infrastructure.providers.mock_error import MockErrorProvider
from app.infrastructure.providers.mock_fast import MockFastProvider
from app.infrastructure.providers.mock_slow import MockSlowProvider
from app.infrastructure.providers.mock_stable import MockStableProvider
from app.infrastructure.providers.openai_compatible import OpenAICompatibleProvider


def _behavior_from(config: ProviderConfig) -> ProviderBehavior:
    return ProviderBehavior(
        latency_ms=config.behavior.latency_ms,
        error_rate=config.behavior.error_rate,
        timeout_ms=config.behavior.timeout_ms,
        default_response=config.behavior.default_response,
    )


def build_provider_registry(
    provider_configs: dict[str, ProviderConfig],
) -> dict[str, ProviderPort]:
    """Build a registry of ProviderPort instances from configs."""
    registry: dict[str, ProviderPort] = {}

    for provider_id, config in provider_configs.items():
        if not config.enabled:
            continue

        behavior = _behavior_from(config)

        if config.type == ProviderType.OPENAI_COMPATIBLE.value:
            registry[provider_id] = OpenAICompatibleProvider(
                provider_id=provider_id, http=config.http, behavior=behavior
            )
            continue

        if config.type == ProviderType.FAKE_STATIC.value:
            registry[provider_id] = FakeStaticProvider(behavior=behavior)
            continue

        # mock type (per-id subclasses; unknown ids fall back to MockFastProvider)
        factory_map: dict[str, type[ProviderPort]] = {
            "mock_fast": MockFastProvider,
            "mock_stable": MockStableProvider,
            "mock_slow": MockSlowProvider,
            "mock_error": MockErrorProvider,
            "fake_static": FakeStaticProvider,
        }
        factory = factory_map.get(provider_id)
        if factory is not None:
            registry[provider_id] = factory(behavior=behavior)
        else:
            registry[provider_id] = BaseMockProvider(
                provider_id=provider_id,
                provider_type=ProviderType.MOCK.value,
                behavior=behavior,
            )

    return registry
