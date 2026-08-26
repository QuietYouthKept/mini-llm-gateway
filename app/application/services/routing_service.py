"""Priority-based routing service.

Resolves a model profile into an ordered list of provider candidates.
"""

from __future__ import annotations

from app.domain.models.model_profile import ModelProfile


class RoutingService:
    """Selects providers based on a model profile's routing strategy."""

    def resolve_candidates(self, profile: ModelProfile) -> list[str]:
        """Return an ordered list of provider IDs for the given profile.

        Currently supports only 'priority' strategy — candidates are sorted
        by their priority value (lower = higher priority).
        """
        routing = profile.routing

        if routing.strategy == "priority":
            if profile.fallback.enabled and profile.fallback.chain:
                # An explicit chain is authoritative and preserves configured order.
                return list(profile.fallback.chain)
            sorted_candidates = sorted(
                routing.candidates,
                key=lambda c: c.priority,
            )
            return [c.provider for c in sorted_candidates]

        raise ValueError(f"Unsupported routing strategy '{routing.strategy}'")
