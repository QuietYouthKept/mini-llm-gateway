"""Shared fixtures for integration tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.container import AppContainer, build_container
from app.infrastructure.config.config_models import AppConfig
from app.infrastructure.persistence.sqlite.connection import init_db
from app.main import create_app


def make_test_config() -> AppConfig:
    return AppConfig.from_dict(
        {
            "gateway": {"default_profile": "fast-chat", "request_timeout_ms": 1500},
            "clients": [
                {
                    "client_id": "demo",
                    "api_key": "demo-key",
                    "enabled": True,
                    "rate_limit": {"requests_per_minute": 1000},
                    "token_budget": {"period": "daily", "max_tokens": 100000},
                },
                {
                    "client_id": "rl",
                    "api_key": "rl-key",
                    "enabled": True,
                    "rate_limit": {"requests_per_minute": 2},
                    "token_budget": {"period": "daily", "max_tokens": 100000},
                },
                {
                    "client_id": "tiny",
                    "api_key": "tiny-key",
                    "enabled": True,
                    "rate_limit": {"requests_per_minute": 1000},
                    "token_budget": {"period": "daily", "max_tokens": 50},
                },
            ],
            "providers": {
                "mock_fast": {
                    "type": "mock",
                    "enabled": True,
                    "behavior": {"latency_ms": 5, "error_rate": 0.0},
                },
                "mock_error": {
                    "type": "mock",
                    "enabled": True,
                    "behavior": {"latency_ms": 5, "error_rate": 1.0},
                },
                "mock_slow": {
                    "type": "mock",
                    "enabled": True,
                    "behavior": {"latency_ms": 10, "error_rate": 0.0, "timeout_ms": 1},
                },
                "fake_static": {
                    "type": "fake_static",
                    "enabled": True,
                    "behavior": {"latency_ms": 5},
                },
            },
            "model_profiles": {
                "fast-chat": {
                    "routing": {
                        "strategy": "priority",
                        "candidates": [
                            {"provider": "mock_fast", "priority": 1},
                            {"provider": "fake_static", "priority": 2},
                        ],
                    },
                    "fallback": {"enabled": True, "chain": ["mock_fast", "fake_static"]},
                },
                "fallback-chat": {
                    "routing": {
                        "strategy": "priority",
                        "candidates": [
                            {"provider": "mock_error", "priority": 1},
                            {"provider": "mock_fast", "priority": 2},
                        ],
                    },
                    "fallback": {"enabled": True, "chain": ["mock_error", "mock_fast"]},
                },
                "timeout-chat": {
                    "routing": {
                        "strategy": "priority",
                        "candidates": [
                            {"provider": "mock_slow", "priority": 1},
                            {"provider": "mock_fast", "priority": 2},
                        ],
                    },
                    "fallback": {"enabled": True, "chain": ["mock_slow", "mock_fast"]},
                },
            },
            "retry": {"max_retries": 1, "base_delay_ms": 5, "max_delay_ms": 20},
            "circuit_breaker": {
                "enabled": True,
                "failure_threshold": 3,
                "recovery_timeout_ms": 500,
            },
            "guardrails": {
                "enabled": True,
                "input_policy": {"max_chars": 4000, "blocked_regex": ["blockme"]},
            },
            "logging": {"persist_replay_payload": True},
            "metrics": {"enabled": True, "prefix": "llm_gateway"},
            "admin": {"enabled": True, "api_key": "admin-key"},
            "observability": {"structured_json_logs": False},
        }
    )


@pytest.fixture
def container(tmp_path) -> AppContainer:
    db = str(tmp_path / "gateway.db")
    init_db(db)
    return build_container(make_test_config(), db)


@pytest.fixture
def client(container: AppContainer) -> TestClient:
    app = create_app(container=container)
    with TestClient(app) as c:
        yield c


def auth(key: str = "demo-key") -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def chat_payload(profile: str, content: str = "hi") -> dict:
    return {
        "profile": profile,
        "messages": [{"role": "user", "content": content}],
    }
