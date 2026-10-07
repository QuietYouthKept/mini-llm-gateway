"""Tests for RoutingService."""

from __future__ import annotations

from app.application.services.routing_service import RoutingService
from app.domain.models.model_profile import (
    ModelProfile,
    RoutingCandidate,
    RoutingConfig,
)


def make_profile(candidates: list[tuple[str, int]]) -> ModelProfile:
    return ModelProfile(
        profile_id="test-profile",
        routing=RoutingConfig(
            strategy="priority",
            candidates=[RoutingCandidate(provider=pid, priority=p) for pid, p in candidates],
        ),
    )


def test_priority_routing_sorts_by_priority() -> None:
    service = RoutingService()
    profile = make_profile(
        [
            ("c", 3),
            ("a", 1),
            ("b", 2),
        ]
    )
    result = service.resolve_candidates(profile)
    assert result == ["a", "b", "c"]


def test_priority_routing_single_candidate() -> None:
    service = RoutingService()
    profile = make_profile([("only", 1)])
    result = service.resolve_candidates(profile)
    assert result == ["only"]


def test_priority_routing_empty_candidates() -> None:
    service = RoutingService()
    profile = make_profile([])
    result = service.resolve_candidates(profile)
    assert result == []


def test_priority_routing_same_priority_preserves_order() -> None:
    service = RoutingService()
    profile = make_profile(
        [
            ("x", 1),
            ("y", 1),
            ("z", 1),
        ]
    )
    result = service.resolve_candidates(profile)
    assert len(result) == 3
    assert set(result) == {"x", "y", "z"}
