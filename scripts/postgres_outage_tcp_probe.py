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
PROJECT = os.environ["WAVE4_COMPOSE_PROJECT"]
BASE_URL = os.environ["WAVE4_BASE_URL"]
IMAGE = os.environ["GATEWAY_IMAGE"]
DATABASE_URL = "postgresql://gateway@postgres:5432/gateway"


def compose(
    *args: str, check: bool = True, image: str | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if image is not None:
        environment["GATEWAY_IMAGE"] = image
    return subprocess.run(
        ["docker", "compose", "-p", PROJECT, *args],
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
            if httpx.get(BASE_URL + "/ready", timeout=3, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise TimeoutError("staging did not become ready")


def request(request_id: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = httpx.post(
            BASE_URL + "/v1/chat",
            headers={"Authorization": "Bearer demo-key", "x-request-id": request_id},
            json={
                "profile": "fast-chat",
                "messages": [{"role": "user", "content": "bounded database outage probe"}],
            },
            timeout=12,
            trust_env=False,
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
        "import json, psycopg; "
        f"c=psycopg.connect({DATABASE_URL!r}); "
        f"r=c.execute({sql!r}, {params!r}).fetchall(); "
        "print(json.dumps(r, default=str)); c.close()"
    )
    return json.loads(compose("exec", "-T", "gateway", "python", "-c", code).stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--concurrencies", nargs="+", type=int, default=[20, 50])
    args = parser.parse_args()
    evidence: dict[str, Any] = {"project": PROJECT, "image": IMAGE, "matrix": []}
    compose("up", "-d", "--no-build", image=IMAGE)
    try:
        wait_ready()
        for concurrency in args.concurrencies:
            compose("exec", "-T", "redis", "redis-cli", "FLUSHDB")
            compose("stop", "postgres")
            time.sleep(1)
            request_ids = [f"wave41-outage-{concurrency}-{uuid.uuid4().hex}" for _ in range(concurrency)]
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(request, request_id) for request_id in request_ids]
                time.sleep(0.05)
                live_started = time.monotonic()
                try:
                    live_status = httpx.get(BASE_URL + "/live", timeout=2, trust_env=False).status_code
                except httpx.HTTPError:
                    live_status = 0
                live_duration = time.monotonic() - live_started
                ready_started = time.monotonic()
                try:
                    ready_status = httpx.get(BASE_URL + "/ready", timeout=4, trust_env=False).status_code
                except httpx.HTTPError:
                    ready_status = 0
                ready_duration = time.monotonic() - ready_started
                results = [future.result() for future in futures]
            logs = compose("logs", "--no-color", "gateway", check=False).stdout[-40000:]
            compose("start", "postgres")
            healthy_deadline = time.monotonic() + 60
            while time.monotonic() < healthy_deadline:
                health = compose("ps", "--format", "{{.Health}}", "postgres", check=False).stdout
                if "healthy" in health:
                    break
                time.sleep(1)
            wait_ready()
            audits = [
                query("SELECT count(*) FROM request_logs WHERE request_id=%s", (request_id,))[0][0]
                for request_id in request_ids
            ]
            reservations = [
                query(
                    "SELECT state FROM token_budget_reservations WHERE reservation_id LIKE %s",
                    (f"{request_id}:%",),
                )
                for request_id in request_ids
            ]
            evidence["matrix"].append(
                {
                    "concurrency": concurrency,
                    "live_status": live_status,
                    "live_duration_seconds": live_duration,
                    "ready_status": ready_status,
                    "ready_duration_seconds": ready_duration,
                    "requests": results,
                    "audit_row_counts": audits,
                    "reservation_states": reservations,
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
            and all(count == 0 for count in item["audit_row_counts"])
            and all(not states for states in item["reservation_states"])
            for item in evidence["matrix"]
        )
    finally:
        compose("down", check=False)
    serialized = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if evidence.get("oracle_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
