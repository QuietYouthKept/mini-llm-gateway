"""Four repeatable, local-only demonstrations of the hardened Gateway."""

from __future__ import annotations

import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.application.services.token_budget_service import TokenBudgetService
from app.core.container import build_container
from app.core.startup import load_config
from app.infrastructure.config.config_models import ClientConfig, TokenBudgetConfig
from app.infrastructure.persistence.sqlite.connection import init_db
from app.infrastructure.persistence.sqlite.repositories import (
    ClientRepository,
    TokenBudgetRepository,
)
from app.main import create_app


def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="mini-llm-gateway-demo-") as temp:
        db = str(Path(temp) / "demo.db")
        init_db(db)
        container = build_container(load_config("config/config.yaml"), db)
        headers = {"Authorization": "Bearer demo-key"}
        with TestClient(create_app(container)) as client:
            happy = client.post(
                "/v1/chat",
                headers=headers,
                json={
                    "profile": "fast-chat",
                    "messages": [{"role": "user", "content": "happy path"}],
                },
            ).json()
            happy_audit = client.get(
                f"/v1/requests/{happy['request_id']}", headers=headers
            ).json()
            fallback = client.post(
                "/v1/chat",
                headers=headers,
                json={
                    "profile": "fallback-chat",
                    "messages": [{"role": "user", "content": "fallback path"}],
                },
            ).json()
            cache_payload = {
                "profile": "fast-chat",
                "messages": [{"role": "user", "content": "exact cache demo"}],
            }
            cache_first = client.post("/v1/chat", headers=headers, json=cache_payload).json()
            cache_second = client.post("/v1/chat", headers=headers, json=cache_payload).json()

        race_db = str(Path(temp) / "race.db")
        init_db(race_db)
        race_client = ClientConfig(
            client_id="demo-race",
            api_key="demo-race-key",
            token_budget=TokenBudgetConfig(period="daily", max_tokens=100),
        )
        ClientRepository(race_db).sync([race_client])
        budget = TokenBudgetService(TokenBudgetRepository(race_db))
        budget.commit(race_client, 80, 0.0)

        def reserve(index: int) -> bool:
            try:
                budget.reserve(f"demo-race-{index}", race_client, 15, 0.0)
                return True
            except Exception:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            admitted = list(pool.map(reserve, (1, 2)))
        snapshot = budget.snapshot(race_client)
        return {
            "demo_1_happy": {
                "provider": happy["provider"],
                "trace_steps": [step["step"] for step in happy["decision_trace"]],
                "audit_attempts": len(happy_audit["attempts"]),
                "pass": happy["provider"] == "mock_fast" and len(happy_audit["attempts"]) == 1,
            },
            "demo_2_fallback": {
                "provider": fallback["provider"],
                "attempt_statuses": [attempt["status"] for attempt in fallback["attempts"]],
                "fallback_used": fallback["fallback_used"],
                "pass": fallback["fallback_used"] and fallback["provider"] == "mock_stable",
            },
            "demo_3_cache": {
                "first_hit": cache_first["cache_hit"],
                "second_hit": cache_second["cache_hit"],
                "second_attempts": cache_second["attempts"],
                "content_equal": cache_first["content"] == cache_second["content"],
                "pass": (
                    not cache_first["cache_hit"]
                    and cache_second["cache_hit"]
                    and cache_second["attempts"] == []
                    and cache_first["content"] == cache_second["content"]
                ),
            },
            "demo_4_budget_concurrency": {
                "admitted": sum(admitted),
                "rejected": 2 - sum(admitted),
                "used_plus_reserved": snapshot.used_tokens + snapshot.reserved_tokens,
                "limit": 100,
                "pass": sum(admitted) == 1 and snapshot.used_tokens + snapshot.reserved_tokens <= 100,
            },
        }


def main() -> int:
    result = run()
    print(json.dumps(result, indent=2))
    return 0 if all(item["pass"] for item in result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
