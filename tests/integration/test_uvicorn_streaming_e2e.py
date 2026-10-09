"""Black-box SSE coverage through a real TCP Uvicorn server.

This deliberately does not use FastAPI's in-process TestClient: it covers the
ASGI send path, socket streaming, and shutdown cleanup used in deployment.
"""

from __future__ import annotations

import os
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
import yaml


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def test_uvicorn_tcp_sse_completes_and_persists_audit(tmp_path) -> None:
    """A streamed response over TCP produces terminal events and one audit row."""
    port = _free_local_port()
    database_path = tmp_path / "uvicorn-gateway.db"
    environment = os.environ.copy()
    environment.update(
        {
            "GW_CONFIG_PATH": "config/config.yaml",
            "GW_DATABASE_PATH": str(database_path),
            "GW_LOG_LEVEL": "WARNING",
        }
    )
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=environment,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base_url, timeout=10.0, trust_env=False) as http:
            for _ in range(100):
                try:
                    if http.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                pytest.fail("Uvicorn did not become healthy within five seconds")

            with http.stream(
                "POST",
                "/v1/chat",
                headers={"Authorization": "Bearer demo-key"},
                json={
                    "profile": "fast-chat",
                    "stream": True,
                    "messages": [{"role": "user", "content": "tcp stream"}],
                },
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                request_id = response.headers["x-request-id"]
                events = "\n".join(response.iter_text())

            assert "event: message" in events
            assert "event: usage" in events
            assert "event: done" in events
            audit = http.get(
                f"/v1/requests/{request_id}",
                headers={"Authorization": "Bearer demo-key"},
            )
            assert audit.status_code == 200
            assert audit.json()["status"] == "completed"
            assert len(audit.json()["attempts"]) == 1

            disconnect_id = f"tcp-disconnect-{uuid.uuid4().hex}"
            observed_message = False
            with http.stream(
                "POST",
                "/v1/chat",
                headers={
                    "Authorization": "Bearer demo-key",
                    "x-request-id": disconnect_id,
                },
                json={
                    "profile": "fast-chat",
                    "stream": True,
                    "messages": [{"role": "user", "content": "disconnect " + "x" * 1400}],
                    "max_tokens": 512,
                },
            ) as response:
                assert response.status_code == 200
                for line in response.iter_lines():
                    if line == "event: message":
                        observed_message = True
                        break
            assert observed_message

            disconnect_audit = None
            for _ in range(100):
                candidate = http.get(
                    f"/v1/requests/{disconnect_id}",
                    headers={"Authorization": "Bearer demo-key"},
                )
                if candidate.status_code == 200:
                    disconnect_audit = candidate.json()
                    break
                time.sleep(0.05)
            assert disconnect_audit is not None
            assert disconnect_audit["status"] == "cancelled"
            assert disconnect_audit["error_code"] == "client_cancelled"
            with sqlite3.connect(database_path) as database:
                finalization = database.execute(
                    "SELECT r.state,f.operation FROM token_budget_reservations r "
                    "JOIN stream_finalizations f USING(reservation_id) "
                    "WHERE f.request_id=?",
                    (disconnect_id,),
                ).fetchone()
                audit_rows = database.execute(
                    "SELECT count(*) FROM request_logs WHERE request_id=?", (disconnect_id,)
                ).fetchone()[0]
                attempt_rows = database.execute(
                    "SELECT status FROM provider_attempts WHERE request_id=?",
                    (disconnect_id,),
                ).fetchall()
            assert finalization is not None
            assert finalization[0] in {"settled", "released"}
            assert finalization[1] in {"settle", "release"}
            assert audit_rows == 1
            assert [row[0] for row in attempt_rows][-1] == "cancelled"
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)


def test_uvicorn_tcp_stream_fallback_timeout_and_post_token_failure(tmp_path) -> None:
    """A real TCP stream audits pre-token fallback and refuses late fallback."""
    provider_port = _free_local_port()
    gateway_port = _free_local_port()
    database_path = tmp_path / "uvicorn-failure-matrix.db"
    config_path = tmp_path / "uvicorn-failure-matrix.yaml"
    raw = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    raw["gateway"]["request_timeout_ms"] = 3000
    raw["retry"]["max_retries"] = 0
    raw["providers"]["fault_stream"] = {
        "type": "openai_compatible",
        "enabled": True,
        "http": {
            "base_url": f"http://127.0.0.1:{provider_port}/v1",
            "model": "fault-fixture",
            "timeout_ms": 80,
            "headers": {"x-fault-mode": "timeout"},
        },
    }
    raw["model_profiles"]["tcp-timeout-fallback"] = {
        "routing": {
            "strategy": "priority",
            "candidates": [
                {"provider": "fault_stream", "priority": 1},
                {"provider": "mock_stable", "priority": 2},
            ],
        },
        "fallback": {
            "enabled": True,
            "trigger_on": ["provider_timeout"],
            "chain": ["fault_stream", "mock_stable"],
        },
    }
    raw["model_profiles"]["tcp-late-failure"] = {
        "routing": {
            "strategy": "priority",
            "candidates": [{"provider": "fault_stream", "priority": 1}],
        },
        "fallback": {"enabled": False, "chain": ["fault_stream"]},
    }
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    provider = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "scripts.fault_provider_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(provider_port),
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    environment = os.environ.copy()
    environment.update(
        {
            "GW_CONFIG_PATH": str(config_path),
            "GW_DATABASE_PATH": str(database_path),
            "GW_LOG_LEVEL": "WARNING",
        }
    )
    gateway = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(gateway_port),
            "--log-level",
            "warning",
            "--no-access-log",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=environment,
    )
    base_url = f"http://127.0.0.1:{gateway_port}"
    try:
        with httpx.Client(base_url=base_url, timeout=10.0, trust_env=False) as http:
            for _ in range(120):
                if gateway.poll() is not None:
                    pytest.fail(f"Gateway exited before startup: {gateway.returncode}")
                if provider.poll() is not None:
                    pytest.fail(f"Fault provider exited before startup: {provider.returncode}")
                try:
                    if http.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)
            else:
                pytest.fail("Uvicorn failure-matrix server did not become healthy")

            with http.stream(
                "POST",
                "/v1/chat",
                headers={"Authorization": "Bearer demo-key"},
                json={
                    "profile": "tcp-timeout-fallback",
                    "stream": True,
                    "messages": [{"role": "user", "content": "timeout before first token"}],
                    "max_tokens": 16,
                },
            ) as response:
                assert response.status_code == 200
                request_id = response.headers["x-request-id"]
                events = "".join(response.iter_text())
            timeout_audit = http.get(
                f"/v1/requests/{request_id}",
                headers={"Authorization": "Bearer demo-key"},
            )
            assert timeout_audit.status_code == 200
            assert "event: message" in events and "event: done" in events
            assert [item["provider_id"] for item in timeout_audit.json()["attempts"]] == [
                "fault_stream",
                "mock_stable",
            ]
            assert timeout_audit.json()["attempts"][0]["status"] == "timeout"
            assert timeout_audit.json()["status"] == "completed"

            raw["providers"]["fault_stream"]["http"]["headers"]["x-fault-mode"] = (
                "stream_then_error"
            )
            config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            # Reload the gateway so the next request uses the late-error fixture.
            gateway.terminate()
            gateway.wait(timeout=10)
            gateway = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(gateway_port),
                    "--log-level",
                    "warning",
                    "--no-access-log",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=environment,
            )
            for _ in range(120):
                try:
                    if http.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.05)

            with http.stream(
                "POST",
                "/v1/chat",
                headers={"Authorization": "Bearer demo-key"},
                json={
                    "profile": "tcp-late-failure",
                    "stream": True,
                    "messages": [{"role": "user", "content": "failure after first token"}],
                    "max_tokens": 16,
                },
            ) as response:
                assert response.status_code == 200
                late_request_id = response.headers["x-request-id"]
                late_events = "".join(response.iter_text())
            late_audit = http.get(
                f"/v1/requests/{late_request_id}",
                headers={"Authorization": "Bearer demo-key"},
            )
            assert late_audit.status_code == 200
            late_body = late_audit.json()
            with sqlite3.connect(database_path) as database:
                finalization = database.execute(
                    "SELECT r.state,f.operation FROM token_budget_reservations r "
                    "JOIN stream_finalizations f USING(reservation_id) "
                    "WHERE f.request_id=?",
                    (late_request_id,),
                ).fetchone()
                audit_rows = database.execute(
                    "SELECT count(*) FROM request_logs WHERE request_id=?", (late_request_id,)
                ).fetchone()[0]
                attempt_rows = database.execute(
                    "SELECT provider_id,status FROM provider_attempts "
                    "WHERE request_id=? ORDER BY attempt_order",
                    (late_request_id,),
                ).fetchall()
            assert "event: message" in late_events and "event: error" in late_events
            assert "event: done" not in late_events
            assert '"code":"provider_failed"' in late_events
            assert late_body["status"] == "partial_provider_error"
            assert late_body["error_code"] == "provider_failed"
            assert finalization == ("settled", "settle")
            assert audit_rows == 1
            assert attempt_rows == [("fault_stream", "error")]
    finally:
        for process in (gateway, provider):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
