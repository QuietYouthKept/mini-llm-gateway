"""Model profile domain model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RoutingCandidate:
    provider: str = ""
    priority: int = 1


@dataclass
class RoutingConfig:
    strategy: str = "priority"
    candidates: list[RoutingCandidate] = field(default_factory=list)


@dataclass
class FallbackConfig:
    enabled: bool = True
    trigger_on: list[str] = field(default_factory=list)
    chain: list[str] = field(default_factory=list)


@dataclass
class ModelProfile:
    profile_id: str = ""
    description: str = ""
    intent: str = ""
    capabilities: dict = field(default_factory=dict)
    preferences: dict = field(default_factory=dict)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)
