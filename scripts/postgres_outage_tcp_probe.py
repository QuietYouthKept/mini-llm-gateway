"""Repeatable real-TCP PostgreSQL outage probe for isolated staging."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "deploy" / "wave5" / "compose.yaml"
PROJECT = os.environ.get("WAVE5_COMPOSE_PROJECT", "mini-llm-gateway-wave5")
BASE_URL = os.environ.get("WAVE5_BASE_URL", "http://127.0.0.1:18150")
IMAGE = os.environ["GATEWAY_IMAGE"]
HTTP_CLIENT = httpx.Client(
    timeout=httpx.Timeout(12.0, connect=2.0, read=10.0, write=4.0, pool=4.0),
    trust_env=False,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=100),
)


def compose(
    *args: str, check: bool = True, image: str | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if image is not None:
        environment["GATEWAY_IMAGE"] = image
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", PROJECT, *args],
        cwd=ROOT,
        env=environment,
        check=check,
        capture_output=True,
        text=True,
        timeout=180,
    )


def wait_ready(timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if HTTP_CLIENT.get(BASE_URL + "/ready", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise TimeoutError("staging did not become ready")


def request(request_id: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = HTTP_CLIENT.post(
            BASE_URL + "/v1/chat",
            headers={"Authorization": "Bearer demo-key", "x-request-id": request_id},
            json={
                "profile": "fast-chat",
                "messages": [{"role": "user", "content": "bounded database outage probe"}],
            },
        )
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text[:500]
        return {
            "status": response.status_code,
            "body": body,
            "duration_seconds": time.monotonic() - started,
        }
    except httpx.HTTPError as exc:
        return {
            "status": 0,
            "body": {"transport_error": type(exc).__name__},
            "duration_seconds": time.monotonic() - started,
        }


def query(sql: str, params: tuple[Any, ...]) -> Any:
    code = (
        "import json, os, psycopg; "
        "c=psycopg.connect(os.environ['GW_DATABASE_URL']); "
        f"r=c.execute({sql!r}, {params!r}).fetchall(); "
        "print(json.dumps(r, default=str)); c.close()"
    )
    return json.loads(compose("exec", "-T", "gateway", "python", "-c", code).stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--concurrencies", nargs="+", type=int, default=[20, 50])
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    evidence: dict[str, Any] = {
        "project": PROJECT,
        "image": IMAGE,
        "base_url": BASE_URL,
        "repetitions": args.repetitions,
        "outage_method": "docker compose kill --signal SIGKILL postgres",
        "matrix": [],
    }
    compose("up", "-d", "--no-build", image=IMAGE)
    try:
        wait_ready()
        for concurrency in args.concurrencies:
            for repetition in range(1, args.repetitions + 1):
                compose("exec", "-T", "redis", "redis-cli", "FLUSHDB")
                compose("kill", "--signal", "SIGKILL", "postgres")
                time.sleep(0.5)
                request_ids = [
                    f"wave5-outage-{concurrency}-{repetition}-{uuid.uuid4().hex}"
                    for _ in range(concurrency)
                ]
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = [pool.submit(request, request_id) for request_id in request_ids]
                    time.sleep(0.05)
                    live_started = time.monotonic()
                    try:
                        live_status = HTTP_CLIENT.get(BASE_URL + "/live", timeout=2).status_code
                    except httpx.HTTPError:
                        live_status = 0
                    live_duration = time.monotonic() - live_started
                    ready_started = time.monotonic()
                    try:
                        ready_status = HTTP_CLIENT.get(BASE_URL + "/ready", timeout=4).status_code
                    except httpx.HTTPError:
                        ready_status = 0
                    ready_duration = time.monotonic() - ready_started
                    results = [future.result() for future in futures]
                try:
                    metrics_text = HTTP_CLIENT.get(BASE_URL + "/metrics", timeout=2).text
                except httpx.HTTPError:
                    metrics_text = ""
                logs = compose("logs", "--no-color", "gateway", check=False).stdout[-40000:]
                compose("up", "-d", "postgres")
                healthy_deadline = time.monotonic() + 60
                while time.monotonic() < healthy_deadline:
                    health = compose(
                        "ps", "--format", "{{.Health}}", "postgres", check=False
                    ).stdout
                    if "healthy" in health:
                        break
                    time.sleep(1)
                wait_ready()
                audit_rows = query(
                    "SELECT request_id, count(*) FROM request_logs "
                    "WHERE request_id = ANY(%s) GROUP BY request_id",
                    (request_ids,),
                )
                audit_counts = {row[0]: row[1] for row in audit_rows}
                audit_details = {
                    request_id: audit_counts.get(request_id, 0)
                    for request_id in request_ids
                }
                reservation_rows = query(
                    "SELECT reservation_id, state FROM token_budget_reservations "
                    "WHERE split_part(reservation_id, ':', 1) = ANY(%s)",
                    (request_ids,),
                )
                reservation_details: dict[str, list[str]] = {
                    request_id: [] for request_id in request_ids
                }
                for reservation_id, state in reservation_rows:
                    request_id = reservation_id.split(":", 1)[0]
                    reservation_details.setdefault(request_id, []).append(state)
                evidence["matrix"].append(
                    {
                        "concurrency": concurrency,
                        "repetition": repetition,
                        "live_status": live_status,
                        "live_duration_seconds": live_duration,
                        "ready_status": ready_status,
                        "ready_duration_seconds": ready_duration,
                        "requests": results,
                        "audit_row_counts": audit_details,
                        "reservation_states": reservation_details,
                        "blocking_io_metrics_excerpt": "\n".join(
                            line
                            for line in metrics_text.splitlines()
                            if any(
                                name in line
                                for name in (
                                    "blocking_io_",
                                    "dependency_circuit_open",
                                    "http_response_start_seconds",
                                    "http_response_complete_seconds",
                                    "event_loop_lag_seconds",
                                    "event_loop_tasks",
                                )
                            )
                        ),
                        "gateway_log_excerpt": logs,
                    }
                )
        evidence["oracle_pass"] = all(
            item["live_status"] == 200
            and item["live_duration_seconds"] < 1
            and item["ready_status"] == 503
            and item["ready_duration_seconds"] < 2
            and all(result["status"] == 503 for result in item["requests"])
            and max(result["duration_seconds"] for result in item["requests"]) < 5
            and all(count == 0 for count in item["audit_row_counts"].values())
            and all(not states for states in item["reservation_states"].values())
            for item in evidence["matrix"]
        )
    finally:
        compose("down", check=False)
        HTTP_CLIENT.close()
    serialized = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if evidence.get("oracle_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
