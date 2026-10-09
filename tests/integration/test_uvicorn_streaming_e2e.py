"""Black-box SSE coverage through a real TCP Uvicorn server.

This deliberately does not use FastAPI's in-process TestClient: it covers the
ASGI send path, socket streaming, and shutdown cleanup used in deployment.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import httpx
import pytest


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
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
