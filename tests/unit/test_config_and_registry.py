"""Tests for AppConfig.from_dict and provider registry building."""

from __future__ import annotations

from app.domain.ports.provider_port import ProviderPort
from app.infrastructure.config.config_models import AppConfig
from app.infrastructure.providers.provider_registry import build_provider_registry


def test_app_config_from_dict_parses_gateway() -> None:
    raw = {
        "gateway": {
            "name": "my-gw",
            "environment": "test",
            "default_profile": "fast-chat",
            "request_timeout_ms": 999,
        },
    }
    config = AppConfig.from_dict(raw)
    assert config.gateway.name == "my-gw"
    assert config.gateway.environment == "test"
    assert config.gateway.default_profile == "fast-chat"
    assert config.gateway.request_timeout_ms == 999


def test_app_config_from_dict_parses_clients() -> None:
    raw = {
        "clients": [
            {
                "client_id": "c1",
                "api_key": "k1",
                "enabled": True,
                "rate_limit": {"requests_per_minute": 10},
                "token_budget": {"period": "daily", "max_tokens": 5000},
            },
        ],
    }
    config = AppConfig.from_dict(raw)
    assert len(config.clients) == 1
    c = config.clients[0]
    assert c.client_id == "c1"
    assert c.api_key == "k1"
    assert c.rate_limit.requests_per_minute == 10
    assert c.token_budget.max_tokens == 5000


def test_app_config_from_dict_parses_providers() -> None:
    raw = {
        "providers": {
            "mock_fast": {
                "type": "mock",
                "enabled": True,
                "behavior": {
                    "latency_ms": 80,
                    "error_rate": 0.0,
                    "timeout_ms": 1000,
                    "default_response": "fast!",
                },
            },
        },
    }
    config = AppConfig.from_dict(raw)
    assert "mock_fast" in config.providers
    p = config.providers["mock_fast"]
    assert p.type == "mock"
    assert p.enabled is True
    assert p.behavior.latency_ms == 80
    assert p.behavior.error_rate == 0.0
    assert p.behavior.default_response == "fast!"


def test_app_config_from_dict_parses_model_profiles() -> None:
    raw = {
        "model_profiles": {
            "fast-chat": {
                "description": "Fast chat profile",
                "intent": "low_latency",
                "routing": {
                    "strategy": "priority",
                    "candidates": [
                        {"provider": "mock_fast", "priority": 1},
                        {"provider": "mock_stable", "priority": 2},
                    ],
                },
                "fallback": {
                    "enabled": True,
                    "trigger_on": ["timeout", "provider_error"],
                    "chain": ["mock_fast", "mock_stable"],
                },
            },
        },
    }
    config = AppConfig.from_dict(raw)
    assert "fast-chat" in config.model_profiles
    mp = config.model_profiles["fast-chat"]
    assert mp.description == "Fast chat profile"
    assert mp.routing.strategy == "priority"
    assert len(mp.routing.candidates) == 2
    assert mp.routing.candidates[0].provider == "mock_fast"
    assert mp.routing.candidates[1].priority == 2
    assert mp.fallback.enabled is True
    assert mp.fallback.chain == ["mock_fast", "mock_stable"]


def test_app_config_from_dict_defaults() -> None:
    config = AppConfig.from_dict({})
    assert config.gateway.name == "mini-llm-gateway"
    assert config.clients == []
    assert config.providers == {}
    assert config.model_profiles == {}


def test_build_provider_registry_creates_correct_instances() -> None:
    raw = {
        "providers": {
            "mock_fast": {
                "type": "mock",
                "enabled": True,
                "behavior": {
                    "latency_ms": 10,
                    "error_rate": 0.0,
                    "timeout_ms": 500,
                    "default_response": "fast",
                },
            },
            "fake_static": {
                "type": "fake_static",
                "enabled": True,
                "behavior": {
                    "latency_ms": 5,
                    "error_rate": 0.0,
                    "timeout_ms": 500,
                    "default_response": "fallback",
                },
            },
            "mock_disabled": {
                "type": "mock",
                "enabled": False,
                "behavior": {},
            },
        },
    }
    config = AppConfig.from_dict(raw)
    registry = build_provider_registry(config.providers)

    assert "mock_fast" in registry
    assert "fake_static" in registry
    assert "mock_disabled" not in registry
    assert isinstance(registry["mock_fast"], ProviderPort)
    assert isinstance(registry["fake_static"], ProviderPort)
    assert registry["mock_fast"].provider_id == "mock_fast"
    assert registry["fake_static"].provider_type == "fake_static"
