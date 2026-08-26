"""Configuration dataclasses.

These mirror the YAML schema and are the single source of truth for what the
gateway can be configured to do. Parsing happens in AppConfig.from_dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ConfigValidationError(ValueError):
    """Raised when configuration is syntactically valid but semantically unsafe."""


def _reject_unknown(raw: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigValidationError(f"Unknown config field(s) at {path}: {', '.join(unknown)}")


@dataclass
class RateLimitConfig:
    requests_per_minute: int = 60


@dataclass
class TokenBudgetConfig:
    period: str = "daily"
    max_tokens: int = 100_000
    max_cost_usd: float = 0.0  # 0 = no cost limit


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
class HTTPProviderConfig:
    """Configuration for a real HTTP (OpenAI-compatible) provider."""

    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""  # prefer reading the key from this env var
    model: str = ""
    timeout_ms: int = 15000
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ProviderConfig:
    provider_id: str = ""
    type: str = "mock"
    enabled: bool = True
    behavior: ProviderBehavior = field(default_factory=ProviderBehavior)
    http: HTTPProviderConfig = field(default_factory=HTTPProviderConfig)


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
    cost_per_1k_input_tokens_usd: float = 0.0
    cost_per_1k_output_tokens_usd: float = 0.0


@dataclass
class LoggingConfig:
    persist_request_body: bool = False
    persist_response_body: bool = False
    # Replay payloads contain the original messages and are therefore opt-in.
    persist_replay_payload: bool = False
    persist_attempts: bool = True
    persist_budget_snapshot: bool = True


@dataclass
class StreamingConfig:
    enabled: bool = False
    behavior_if_requested: str = "reject"  # "reject" | "ignore"


@dataclass
class RetryConfig:
    max_retries: int = 1
    base_delay_ms: int = 50
    max_delay_ms: int = 1000
    retry_on: list[str] = field(
        default_factory=lambda: [
            "provider_timeout",
            "provider_failed",
            "provider_bad_status",
        ]
    )


@dataclass
class CircuitBreakerConfig:
    enabled: bool = True
    failure_threshold: int = 3
    recovery_timeout_ms: int = 5000
    half_open_max_calls: int = 1


@dataclass
class InputPolicyConfig:
    max_chars: int = 4000
    blocked_regex: list[str] = field(default_factory=list)
    pii_detection: bool = False
    prompt_injection: bool = False


@dataclass
class OutputPolicyConfig:
    max_chars: int = 8000
    blocked_terms: list[str] = field(default_factory=list)
    pii_redaction: bool = False


@dataclass
class GuardrailConfig:
    enabled: bool = True
    input_policy: InputPolicyConfig = field(default_factory=InputPolicyConfig)
    output_policy: OutputPolicyConfig = field(default_factory=OutputPolicyConfig)
    audit: bool = True


@dataclass
class MetricsConfig:
    enabled: bool = True
    prefix: str = "llm_gateway"


@dataclass
class AdminConfig:
    enabled: bool = True
    api_key: str = "admin-key"


@dataclass
class ObservabilityConfig:
    structured_json_logs: bool = True
    tracing_enabled: bool = True
    max_spans: int = 2048


@dataclass
class CacheConfig:
    enabled: bool = True
    max_entries: int = 256
    ttl_ms: int = 300_000


@dataclass
class ReplayConfig:
    allow_live: bool = False


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
    retry: RetryConfig = field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    replay: ReplayConfig = field(default_factory=ReplayConfig)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AppConfig:
        """Build an AppConfig from a raw YAML dictionary."""
        _reject_unknown(
            raw,
            {
                "gateway",
                "clients",
                "providers",
                "model_profiles",
                "token_estimation",
                "logging",
                "streaming",
                "retry",
                "circuit_breaker",
                "guardrails",
                "metrics",
                "admin",
                "observability",
                "cache",
                "replay",
            },
            "root",
        )
        gw = raw.get("gateway", {})
        _reject_unknown(
            gw,
            {"name", "environment", "default_profile", "request_timeout_ms"},
            "gateway",
        )
        gateway = GatewayConfig(
            name=gw.get("name", "mini-llm-gateway"),
            environment=gw.get("environment", "local"),
            default_profile=gw.get("default_profile", ""),
            request_timeout_ms=gw.get("request_timeout_ms", 1500),
        )

        clients = [
            ClientConfig(
                client_id=c.get("client_id", ""),
                api_key=c.get("api_key", ""),
                enabled=c.get("enabled", True),
                rate_limit=RateLimitConfig(
                    requests_per_minute=c.get("rate_limit", {}).get(
                        "requests_per_minute", 60
                    )
                ),
                token_budget=TokenBudgetConfig(
                    period=c.get("token_budget", {}).get("period", "daily"),
                    max_tokens=c.get("token_budget", {}).get("max_tokens", 100_000),
                    max_cost_usd=c.get("token_budget", {}).get("max_cost_usd", 0.0),
                ),
            )
            for c in raw.get("clients", [])
        ]
        for index, client_raw in enumerate(raw.get("clients", [])):
            _reject_unknown(
                client_raw,
                {"client_id", "api_key", "enabled", "rate_limit", "token_budget"},
                f"clients[{index}]",
            )
            _reject_unknown(
                client_raw.get("rate_limit", {}),
                {"requests_per_minute"},
                f"clients[{index}].rate_limit",
            )
            _reject_unknown(
                client_raw.get("token_budget", {}),
                {"period", "max_tokens", "max_cost_usd"},
                f"clients[{index}].token_budget",
            )

        providers: dict[str, ProviderConfig] = {}
        for pid, pdata in raw.get("providers", {}).items():
            _reject_unknown(pdata, {"type", "enabled", "behavior", "http"}, f"providers.{pid}")
            behavior_raw = pdata.get("behavior", {})
            http_raw = pdata.get("http", {})
            _reject_unknown(
                behavior_raw,
                {"latency_ms", "error_rate", "timeout_ms", "default_response"},
                f"providers.{pid}.behavior",
            )
            _reject_unknown(
                http_raw,
                {"base_url", "api_key", "api_key_env", "model", "timeout_ms", "headers"},
                f"providers.{pid}.http",
            )
            providers[pid] = ProviderConfig(
                provider_id=pid,
                type=pdata.get("type", "mock"),
                enabled=pdata.get("enabled", True),
                behavior=ProviderBehavior(
                    latency_ms=behavior_raw.get("latency_ms", 100),
                    error_rate=behavior_raw.get("error_rate", 0.0),
                    timeout_ms=behavior_raw.get("timeout_ms", 1000),
                    default_response=behavior_raw.get("default_response", ""),
                ),
                http=HTTPProviderConfig(
                    base_url=http_raw.get("base_url", ""),
                    api_key=http_raw.get("api_key", ""),
                    api_key_env=http_raw.get("api_key_env", ""),
                    model=http_raw.get("model", ""),
                    timeout_ms=http_raw.get("timeout_ms", 15000),
                    headers=http_raw.get("headers", {}),
                ),
            )

        model_profiles: dict[str, ModelProfileConfig] = {}
        for mid, mdata in raw.get("model_profiles", {}).items():
            _reject_unknown(
                mdata,
                {"description", "intent", "capabilities", "preferences", "routing", "fallback"},
                f"model_profiles.{mid}",
            )
            routing_raw = mdata.get("routing", {})
            fallback_raw = mdata.get("fallback", {})
            _reject_unknown(
                routing_raw,
                {"strategy", "candidates"},
                f"model_profiles.{mid}.routing",
            )
            _reject_unknown(
                fallback_raw,
                {"enabled", "trigger_on", "chain"},
                f"model_profiles.{mid}.fallback",
            )
            model_profiles[mid] = ModelProfileConfig(
                profile_id=mid,
                description=mdata.get("description", ""),
                intent=mdata.get("intent", ""),
                capabilities=mdata.get("capabilities", {}),
                preferences=mdata.get("preferences", {}),
                routing=RoutingConfig(
                    strategy=routing_raw.get("strategy", "priority"),
                    candidates=[
                        RoutingCandidate(
                            provider=rc.get("provider", ""),
                            priority=rc.get("priority", 1),
                        )
                        for rc in routing_raw.get("candidates", [])
                    ],
                ),
                fallback=FallbackConfig(
                    enabled=fallback_raw.get("enabled", True),
                    trigger_on=fallback_raw.get("trigger_on", []),
                    chain=fallback_raw.get("chain", []),
                ),
            )

        te = raw.get("token_estimation", {})
        _reject_unknown(
            te,
            {
                "strategy",
                "chars_per_token",
                "min_tokens",
                "cost_per_1k_input_tokens_usd",
                "cost_per_1k_output_tokens_usd",
            },
            "token_estimation",
        )
        token_estimation = TokenEstimationConfig(
            strategy=te.get("strategy", "heuristic"),
            chars_per_token=te.get("chars_per_token", 4),
            min_tokens=te.get("min_tokens", 1),
            cost_per_1k_input_tokens_usd=te.get("cost_per_1k_input_tokens_usd", 0.0),
            cost_per_1k_output_tokens_usd=te.get("cost_per_1k_output_tokens_usd", 0.0),
        )

        lg = raw.get("logging", {})
        _reject_unknown(
            lg,
            {
                "persist_request_body",
                "persist_response_body",
                "persist_replay_payload",
                "persist_attempts",
                "persist_budget_snapshot",
            },
            "logging",
        )
        logging_config = LoggingConfig(
            persist_request_body=lg.get("persist_request_body", False),
            persist_response_body=lg.get("persist_response_body", False),
            persist_replay_payload=lg.get("persist_replay_payload", False),
            persist_attempts=lg.get("persist_attempts", True),
            persist_budget_snapshot=lg.get("persist_budget_snapshot", True),
        )

        st = raw.get("streaming", {})
        _reject_unknown(st, {"enabled", "behavior_if_requested"}, "streaming")
        streaming = StreamingConfig(
            enabled=st.get("enabled", False),
            behavior_if_requested=st.get("behavior_if_requested", "reject"),
        )

        rt = raw.get("retry", {})
        _reject_unknown(
            rt, {"max_retries", "base_delay_ms", "max_delay_ms", "retry_on"}, "retry"
        )
        retry = RetryConfig(
            max_retries=rt.get("max_retries", 1),
            base_delay_ms=rt.get("base_delay_ms", 50),
            max_delay_ms=rt.get("max_delay_ms", 1000),
            retry_on=rt.get(
                "retry_on", ["provider_timeout", "provider_failed", "provider_bad_status"]
            ),
        )

        cb = raw.get("circuit_breaker", {})
        _reject_unknown(
            cb,
            {"enabled", "failure_threshold", "recovery_timeout_ms", "half_open_max_calls"},
            "circuit_breaker",
        )
        circuit_breaker = CircuitBreakerConfig(
            enabled=cb.get("enabled", True),
            failure_threshold=cb.get("failure_threshold", 3),
            recovery_timeout_ms=cb.get("recovery_timeout_ms", 5000),
            half_open_max_calls=cb.get("half_open_max_calls", 1),
        )

        gd = raw.get("guardrails", {})
        _reject_unknown(gd, {"enabled", "input_policy", "output_policy", "audit"}, "guardrails")
        in_raw = gd.get("input_policy", {})
        out_raw = gd.get("output_policy", {})
        _reject_unknown(
            in_raw,
            {"max_chars", "blocked_regex", "pii_detection", "prompt_injection"},
            "guardrails.input_policy",
        )
        _reject_unknown(
            out_raw,
            {"max_chars", "blocked_terms", "pii_redaction"},
            "guardrails.output_policy",
        )
        guardrails = GuardrailConfig(
            enabled=gd.get("enabled", True),
            input_policy=InputPolicyConfig(
                max_chars=in_raw.get("max_chars", 4000),
                blocked_regex=in_raw.get("blocked_regex", []),
                pii_detection=in_raw.get("pii_detection", False),
                prompt_injection=in_raw.get("prompt_injection", False),
            ),
            output_policy=OutputPolicyConfig(
                max_chars=out_raw.get("max_chars", 8000),
                blocked_terms=out_raw.get("blocked_terms", []),
                pii_redaction=out_raw.get("pii_redaction", False),
            ),
            audit=gd.get("audit", True),
        )

        mt = raw.get("metrics", {})
        _reject_unknown(mt, {"enabled", "prefix"}, "metrics")
        metrics = MetricsConfig(
            enabled=mt.get("enabled", True),
            prefix=mt.get("prefix", "llm_gateway"),
        )

        ad = raw.get("admin", {})
        _reject_unknown(ad, {"enabled", "api_key"}, "admin")
        admin = AdminConfig(
            enabled=ad.get("enabled", True),
            api_key=ad.get("api_key", "admin-key"),
        )

        ob = raw.get("observability", {})
        _reject_unknown(
            ob, {"structured_json_logs", "tracing_enabled", "max_spans"}, "observability"
        )
        observability = ObservabilityConfig(
            structured_json_logs=ob.get("structured_json_logs", True),
            tracing_enabled=ob.get("tracing_enabled", True),
            max_spans=ob.get("max_spans", 2048),
        )

        ca = raw.get("cache", {})
        _reject_unknown(ca, {"enabled", "max_entries", "ttl_ms"}, "cache")
        cache = CacheConfig(
            enabled=ca.get("enabled", True),
            max_entries=ca.get("max_entries", 256),
            ttl_ms=ca.get("ttl_ms", 300_000),
        )

        replay_raw = raw.get("replay", {})
        _reject_unknown(replay_raw, {"allow_live"}, "replay")
        replay = ReplayConfig(allow_live=replay_raw.get("allow_live", False))

        config = cls(
            gateway=gateway,
            clients=clients,
            providers=providers,
            model_profiles=model_profiles,
            token_estimation=token_estimation,
            logging=logging_config,
            streaming=streaming,
            retry=retry,
            circuit_breaker=circuit_breaker,
            guardrails=guardrails,
            metrics=metrics,
            admin=admin,
            observability=observability,
            cache=cache,
            replay=replay,
        )
        config.validate(check_references="providers" in raw and "model_profiles" in raw)
        return config

    def validate(self, *, check_references: bool = True) -> None:
        if self.gateway.request_timeout_ms <= 0:
            raise ConfigValidationError("gateway.request_timeout_ms must be positive")
        if (
            check_references
            and self.gateway.default_profile
            and self.gateway.default_profile not in self.model_profiles
        ):
            raise ConfigValidationError(
                f"Unknown gateway.default_profile '{self.gateway.default_profile}'"
            )
        supported_provider_types = {"mock", "fake_static", "openai_compatible"}
        client_ids = [client.client_id for client in self.clients]
        api_keys = [client.api_key for client in self.clients if client.enabled and client.api_key]
        if len(client_ids) != len(set(client_ids)):
            raise ConfigValidationError("Duplicate client_id values are not allowed")
        if len(api_keys) != len(set(api_keys)):
            raise ConfigValidationError("Duplicate enabled client api_key values are not allowed")
        for client in self.clients:
            if not client.client_id:
                raise ConfigValidationError("client_id must not be empty")
            if client.rate_limit.requests_per_minute < 0:
                raise ConfigValidationError("requests_per_minute must not be negative")
            if client.token_budget.max_tokens < 0:
                raise ConfigValidationError("token_budget.max_tokens must not be negative")
        for provider_id, provider in self.providers.items():
            if provider.type not in supported_provider_types:
                raise ConfigValidationError(
                    f"Unknown provider type '{provider.type}' for '{provider_id}'"
                )
            if provider.type == "openai_compatible" and not provider.http.base_url:
                raise ConfigValidationError(
                    f"Provider '{provider_id}' requires http.base_url"
                )
        allowed_retry = {"provider_timeout", "provider_failed", "provider_bad_status"}
        invalid_retry = sorted(set(self.retry.retry_on) - allowed_retry)
        if invalid_retry:
            raise ConfigValidationError(
                "Unknown retry.retry_on value(s): " + ", ".join(invalid_retry)
            )
        if self.streaming.behavior_if_requested not in {"reject", "ignore"}:
            raise ConfigValidationError(
                "streaming.behavior_if_requested must be 'reject' or 'ignore'"
            )
        enabled = {pid for pid, provider in self.providers.items() if provider.enabled}
        allowed_triggers = {
            "provider_error",
            "provider_failed",
            "timeout",
            "provider_timeout",
            "bad_status",
            "provider_bad_status",
        }
        for profile_id, profile in self.model_profiles.items():
            if profile.routing.strategy != "priority":
                raise ConfigValidationError(
                    f"Unknown routing strategy '{profile.routing.strategy}' in '{profile_id}'"
                )
            candidate_ids = [candidate.provider for candidate in profile.routing.candidates]
            referenced = candidate_ids + profile.fallback.chain
            unknown = (
                sorted({provider for provider in referenced if provider not in enabled})
                if check_references
                else []
            )
            if unknown:
                raise ConfigValidationError(
                    f"Profile '{profile_id}' references unknown/disabled provider(s): "
                    + ", ".join(unknown)
                )
            invalid_triggers = sorted(set(profile.fallback.trigger_on) - allowed_triggers)
            if invalid_triggers:
                raise ConfigValidationError(
                    f"Profile '{profile_id}' has unknown fallback.trigger_on value(s): "
                    + ", ".join(invalid_triggers)
                )
            if profile.fallback.enabled and not (profile.fallback.chain or candidate_ids):
                raise ConfigValidationError(
                    f"Profile '{profile_id}' has fallback enabled but no providers"
                )
