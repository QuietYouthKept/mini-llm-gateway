from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 60


@dataclass
class TokenBudgetConfig:
    period: str = "daily"
    max_tokens: int = 100_000


@dataclass
class ClientConfig:
    client_id: str = ""
    api_key: str = ""
    enabled: bool = True
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    token_budget: TokenBudgetConfig = field(default_factory=TokenBudgetConfig)


@dataclass
class ProviderBehavior:
    latency_ms: int = 100
    error_rate: float = 0.0
    timeout_ms: int = 1000
    default_response: str = ""


@dataclass
class ProviderConfig:
    provider_id: str = ""
    type: str = "mock"
    enabled: bool = True
    behavior: ProviderBehavior = field(default_factory=ProviderBehavior)


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
class ModelProfileConfig:
    profile_id: str = ""
    description: str = ""
    intent: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, str] = field(default_factory=dict)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    fallback: FallbackConfig = field(default_factory=FallbackConfig)


@dataclass
class TokenEstimationConfig:
    strategy: str = "heuristic"
    chars_per_token: int = 4
    min_tokens: int = 1


@dataclass
class LoggingConfig:
    persist_request_body: bool = False
    persist_response_body: bool = False
    persist_attempts: bool = True
    persist_budget_snapshot: bool = True


@dataclass
class StreamingConfig:
    enabled: bool = False
    behavior_if_requested: str = "reject"


@dataclass
class GatewayConfig:
    name: str = "mini-llm-gateway"
    environment: str = "local"
    default_profile: str = ""
    request_timeout_ms: int = 1500


@dataclass
class AppConfig:
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    clients: list[ClientConfig] = field(default_factory=list)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    model_profiles: dict[str, ModelProfileConfig] = field(default_factory=dict)
    token_estimation: TokenEstimationConfig = field(
        default_factory=TokenEstimationConfig
    )
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
