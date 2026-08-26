"""Mapping from config dataclasses to domain models."""

from __future__ import annotations

from app.domain.models.model_profile import (
    FallbackConfig,
    ModelProfile,
    RoutingCandidate,
    RoutingConfig,
)
from app.infrastructure.config.config_models import (
    ModelProfileConfig,
)


def profile_config_to_domain(profile_id: str, cfg: ModelProfileConfig) -> ModelProfile:
    """Convert a ModelProfileConfig into a domain ModelProfile."""
    return ModelProfile(
        profile_id=profile_id,
        description=cfg.description,
        intent=cfg.intent,
        capabilities=cfg.capabilities,
        preferences=cfg.preferences,
        routing=RoutingConfig(
            strategy=cfg.routing.strategy,
            candidates=[
                RoutingCandidate(provider=c.provider, priority=c.priority)
                for c in cfg.routing.candidates
            ],
        ),
        fallback=FallbackConfig(
            enabled=cfg.fallback.enabled,
            trigger_on=cfg.fallback.trigger_on,
            chain=cfg.fallback.chain,
        ),
    )
