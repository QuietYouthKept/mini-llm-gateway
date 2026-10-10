"""Offline deterministic demo for chat, fallback, SSE, audit, and metrics."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.core.container import build_container
from app.infrastructure.config.config_models import AppConfig
from app.infrastructure.config.yaml_config_loader import YamlConfigLoader
from app.infrastructure.persistence.sqlite.connection import init_db
from app.main import create_app


def _exercise(client, api_key: str, gateway: str, mode: str) -> dict[str, object]:  # noqa: ANN001
    headers = {"Authorization": f"Bearer {api_key}"}
    scenarios: list[dict[str, object]] = []
    ready_response = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            ready_response = client.get("/ready")
            if ready_response.status_code == 200:
                break
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    if ready_response is None or ready_response.status_code != 200:
        status = ready_response.status_code if ready_response is not None else "unreachable"
        raise RuntimeError(f"Gateway did not become ready within 10 seconds: {status}")

    for name, profile in (("normal", "fast-chat"), ("provider-fallback", "fallback-chat")):
        response = client.post(
            "/v1/chat",
            headers=headers,
            json={
                "profile": profile,
                "messages": [{"role": "user", "content": f"synthetic {name} demo"}],
                "max_tokens": 32,
            },
        )
        response.raise_for_status()
        body = response.json()
        request_id = body["request_id"]
        audit = client.get(f"/v1/requests/{request_id}", headers=headers)
        audit.raise_for_status()
        audit_body = audit.json()
        scenarios.append(
            {
                "name": name,
                "request_id": request_id,
                "provider": body.get("provider"),
                "fallback_used": body.get("fallback_used"),
                "attempts": [
                    {
                        "provider_id": item.get("provider_id"),
                        "attempt_order": item.get("attempt_order"),
                        "status": item.get("status"),
                        "error_code": item.get("error_code"),
                        "provider_request_id_present": bool(item.get("provider_request_id")),
                    }
                    for item in audit_body.get("attempts", [])
                ],
                "audit_status": audit_body.get("status"),
                "decision_steps": [
                    item.get("step") for item in audit_body.get("decision_trace", [])
                ],
            }
        )

    stream_response = client.post(
        "/v1/chat",
        headers=headers,
        json={
            "profile": "fast-chat",
            "stream": True,
            "messages": [{"role": "user", "content": "synthetic SSE demo"}],
            "max_tokens": 32,
        },
    )
    stream_response.raise_for_status()
    event_names = [
        line.removeprefix("event: ").strip()
        for line in stream_response.text.splitlines()
        if line.startswith("event: ")
    ]
    stream_request_id = stream_response.headers.get("x-request-id", "")
    stream_audit = client.get(f"/v1/requests/{stream_request_id}", headers=headers)
    stream_audit.raise_for_status()
    scenarios.append(
        {
            "name": "streaming",
            "request_id": stream_request_id,
            "events": event_names,
            "audit_status": stream_audit.json().get("status"),
            "attempt_count": len(stream_audit.json().get("attempts", [])),
        }
    )

    metrics_response = client.get("/metrics")
    metrics_response.raise_for_status()
    metric_names = sorted(
        {
            line.split("{", 1)[0].split(" ", 1)[0]
            for line in metrics_response.text.splitlines()
            if line.startswith("llm_gateway_")
        }
    )
    return {
        "mode": mode,
        "gateway": gateway,
        "readiness": ready_response.json(),
        "scenarios": scenarios,
        "metric_families_observed": metric_names,
        "paid_provider_used": False,
        "privacy": "prompts and completions are omitted from this report",
    }


def run(base_url: str | None = None, api_key: str = "demo-key") -> dict[str, object]:
    if base_url:
        with httpx.Client(
            base_url=base_url.rstrip("/"), timeout=15.0, trust_env=False
        ) as client:
            return _exercise(client, api_key, base_url.rstrip("/"), "live-http")

    # Make the default mode independent of Redis, OTLP, host state, and paid APIs.
    env = {
        "GW_REDIS_URL": "",
        "GW_CACHE_BACKEND": "local",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "",
        "GW_AUTO_MIGRATE": "",
    }
    with tempfile.TemporaryDirectory(prefix="gateway-resume-demo-") as directory:
        database_path = str(Path(directory) / "demo.db")
        with patch.dict(os.environ, env):
            raw = YamlConfigLoader(config_path="config/config.yaml").load()
            config = AppConfig.from_dict(raw)
            init_db(database_path)
            container = build_container(config, database_path)
            with TestClient(create_app(container=container)) as client:
                return _exercise(client, api_key, "temporary SQLite + deterministic providers", "offline")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.getenv("GW_DEMO_URL") or None,
        help="optional running gateway URL; omit for the default offline deterministic demo",
    )
    parser.add_argument("--api-key", default=os.getenv("GW_DEMO_API_KEY", "demo-key"))
    args = parser.parse_args()
    print(json.dumps(run(args.url, args.api_key), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
