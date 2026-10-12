"""Extended real-TCP contract test; requires an explicitly supplied Toxiproxy binary."""

from __future__ import annotations

import json
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

TOXIPROXY_SERVER = os.getenv("TOXIPROXY_SERVER")
pytestmark = pytest.mark.skipif(
    not TOXIPROXY_SERVER,
    reason="extended TCP chaos test requires TOXIPROXY_SERVER",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, process: subprocess.Popen, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=0.25, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"service exited early with code {process.returncode}")
            try:
                response = client.get(url)
                if response.status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.05)
    raise AssertionError(f"service did not become healthy: {url}")


def _start_uvicorn(repo: Path, port: int, app: str, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", app, "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning", "--no-access-log"],
        cwd=repo,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _stop(process: subprocess.Popen | None) -> str:
    if process is None:
        return ""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if process.stderr is None:
        return ""
    return process.stderr.read().decode("utf-8", errors="replace")[-4000:]


def test_client_observed_three_chunks_then_toxiproxy_resets_upstream(
    tmp_path: Path,
) -> None:
    """After three client-visible chunks, reset A and forbid transparent B fallback."""
    repo = Path(__file__).resolve().parents[2]
    evidence_dir = (
        Path(os.environ["WAVE6_EVIDENCE_DIR"]) if os.getenv("WAVE6_EVIDENCE_DIR") else None
    )
    provider_a_port, provider_b_port = _free_port(), _free_port()
    gateway_port, proxy_port, toxiproxy_api_port = _free_port(), _free_port(), _free_port()
    database_path = tmp_path / "three-chunk-reset.sqlite"
    config_path = tmp_path / "three-chunk-reset.yaml"
    proxy_name = f"gateway-fault-{uuid.uuid4().hex[:10]}"
    toxiproxy = provider_a = provider_b = gateway = None
    results: dict[str, object] = {
        "scenario_id": "post-token-three-client-chunks-reset-peer-v1",
        "fault": (
            "Toxiproxy reset_peer downstream, activated after the client parsed "
            "3 message events"
        ),
        "seed": 20261012,
        "source_sha": os.getenv("WAVE6_SOURCE_SHA", "unknown"),
        "executed": False,
    }
    stderr: dict[str, str] = {}
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repo)
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    environment["no_proxy"] = environment["NO_PROXY"]
    try:
        toxiproxy = subprocess.Popen(
            [TOXIPROXY_SERVER, "-host", "127.0.0.1", "-port", str(toxiproxy_api_port),
             "-seed", "20261012"],
            cwd=repo,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _wait_http(f"http://127.0.0.1:{toxiproxy_api_port}/version", toxiproxy)

        provider_env = environment.copy()
        provider_a = _start_uvicorn(
            repo, provider_a_port, "scripts.fault_provider_app:app", provider_env
        )
        provider_b = _start_uvicorn(
            repo, provider_b_port, "scripts.fault_provider_app:app", provider_env
        )
        _wait_http(f"http://127.0.0.1:{provider_a_port}/health", provider_a)
        _wait_http(f"http://127.0.0.1:{provider_b_port}/health", provider_b)

        toxiproxy_url = f"http://127.0.0.1:{toxiproxy_api_port}"
        with httpx.Client(base_url=toxiproxy_url, trust_env=False, timeout=2.0) as control:
            created = control.post(
                "/proxies",
                json={
                    "name": proxy_name,
                    "listen": f"127.0.0.1:{proxy_port}",
                    "upstream": f"127.0.0.1:{provider_a_port}",
                    "enabled": True,
                },
            )
            assert created.status_code in {200, 201}

        raw = yaml.safe_load((repo / "config" / "config.yaml").read_text(encoding="utf-8"))
        raw["gateway"]["request_timeout_ms"] = 12000
        raw["retry"]["max_retries"] = 0
        raw["providers"]["fault_stream_a"] = {
            "type": "openai_compatible",
            "enabled": True,
            "http": {
                "base_url": f"http://127.0.0.1:{proxy_port}/v1",
                "model": "fault-fixture",
                "timeout_ms": 10000,
                "allow_private_network": True,
                "headers": {"x-fault-mode": "stream_3_chunks_reset_trigger"},
            },
        }
        raw["providers"]["fault_stream_b"] = {
            "type": "openai_compatible",
            "enabled": True,
            "http": {
                "base_url": f"http://127.0.0.1:{provider_b_port}/v1",
                "model": "fault-fixture",
                "timeout_ms": 5000,
                "allow_private_network": True,
            },
        }
        raw["model_profiles"]["post-token-reset"] = {
            "routing": {
                "strategy": "priority",
                "candidates": [
                    {"provider": "fault_stream_a", "priority": 1},
                    {"provider": "fault_stream_b", "priority": 2},
                ],
            },
            "fallback": {
                "enabled": True,
                "trigger_on": ["provider_timeout", "provider_failed", "provider_bad_status"],
                "chain": ["fault_stream_a", "fault_stream_b"],
            },
        }
        config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        gateway_env = environment.copy()
        gateway_env.update(
            {
                "GW_CONFIG_PATH": str(config_path),
                "GW_DATABASE_PATH": str(database_path),
                "GW_LOG_LEVEL": "WARNING",
            }
        )
        gateway = _start_uvicorn(repo, gateway_port, "app.main:app", gateway_env)
        base_url = f"http://127.0.0.1:{gateway_port}"
        _wait_http(f"{base_url}/health", gateway)

        client_chunks: list[str] = []
        event_names: list[str] = []
        event_data: list[dict] = []
        request_id = ""
        with (
            httpx.Client(base_url=base_url, timeout=15.0, trust_env=False) as client,
            client.stream(
                "POST",
                "/v1/chat",
                headers={"Authorization": "Bearer demo-key"},
                json={
                    "profile": "post-token-reset",
                    "stream": True,
                    "messages": [{"role": "user", "content": "synthetic reset case"}],
                    "max_tokens": 32,
                },
            ) as response,
        ):
                assert response.status_code == 200
                request_id = response.headers["x-request-id"]
                current_event = ""
                injected = False
                for line in response.iter_lines():
                    if line.startswith("event: "):
                        current_event = line.removeprefix("event: ")
                        event_names.append(current_event)
                    elif line.startswith("data: "):
                        data = json.loads(line.removeprefix("data: "))
                        event_data.append(data)
                        if current_event == "message":
                            chunk = data.get("delta", "")
                            if chunk:
                                client_chunks.append(chunk)
                        if len(client_chunks) == 3 and not injected:
                            assert client_chunks == [
                                "fault-chunk-1", "fault-chunk-2", "fault-chunk-3"
                            ]
                            with httpx.Client(
                                base_url=toxiproxy_url, trust_env=False, timeout=2.0
                            ) as control:
                                toxic = control.post(
                                    f"/proxies/{proxy_name}/toxics",
                                    json={
                                        "name": "reset-after-client-chunk-three",
                                        "type": "reset_peer",
                                        "stream": "downstream",
                                        "toxicity": 1.0,
                                        "attributes": {"timeout": 0},
                                    },
                                )
                            toxic.raise_for_status()
                            results["toxic_config"] = toxic.json()
                            injected = True
                            results["injection_after_client_chunks"] = len(client_chunks)
                        if current_event == "error":
                            break

        assert client_chunks == ["fault-chunk-1", "fault-chunk-2", "fault-chunk-3"]
        assert "error" in event_names
        assert "done" not in event_names
        error = next(
            data for event, data in zip(event_names, event_data, strict=True) if event == "error"
        )
        assert error["code"] == "provider_failed"

        with httpx.Client(trust_env=False, timeout=2.0) as client:
            audit_response = client.get(
                f"{base_url}/v1/requests/{request_id}",
                headers={"Authorization": "Bearer demo-key"},
            )
            b_stats = client.get(f"http://127.0.0.1:{provider_b_port}/stats").json()
            a_stats = client.get(f"http://127.0.0.1:{provider_a_port}/stats").json()
        assert audit_response.status_code == 200
        audit = audit_response.json()
        with sqlite3.connect(database_path) as database:
            finalization = database.execute(
                "SELECT r.state,f.operation FROM token_budget_reservations r "
                "JOIN stream_finalizations f USING(reservation_id) WHERE f.request_id=?",
                (request_id,),
            ).fetchone()
            audit_count = database.execute(
                "SELECT count(*) FROM request_logs WHERE request_id=?", (request_id,)
            ).fetchone()[0]
            attempts = database.execute(
                "SELECT provider_id,status FROM provider_attempts "
                "WHERE request_id=? ORDER BY attempt_order",
                (request_id,),
            ).fetchall()
        assert audit["status"] == "partial_provider_error"
        assert finalization == ("settled", "settle")
        assert audit_count == 1
        assert attempts == [("fault_stream_a", "error")]
        assert b_stats["requests"] == 0
        assert a_stats["requests"] == 1

        results.update(
            {
                "executed": True,
                "request_id": request_id,
                "client_chunks": client_chunks,
                "sse_events": event_names,
                "error_code": error["code"],
                "audit_status": audit["status"],
                "provider_attempts": attempts,
                "provider_a_stats": a_stats,
                "provider_b_stats": b_stats,
                "reservation_finalization": finalization,
                "request_audit_rows": audit_count,
                "verdict": "PASS",
            }
        )
    except Exception as exc:
        results["verdict"] = "FAIL"
        results["failure_type"] = type(exc).__name__
        results["failure"] = str(exc)
        raise
    finally:
        stderr["gateway"] = _stop(gateway)
        stderr["provider_a"] = _stop(provider_a)
        stderr["provider_b"] = _stop(provider_b)
        stderr["toxiproxy"] = _stop(toxiproxy)
        results["service_stderr_tail"] = stderr
        if evidence_dir is not None:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            evidence_path = evidence_dir / f"post-token-three-chunk-reset-{time.time_ns()}.json"
            evidence_path.write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
