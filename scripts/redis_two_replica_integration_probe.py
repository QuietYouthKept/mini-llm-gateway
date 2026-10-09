"""Run cross-replica Redis probes against two real Uvicorn processes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.infrastructure.persistence.postgresql.connection import connect
from scripts.distributed_singleflight_probe import probe as probe_singleflight
from scripts.redis_replica_probe import run as probe_replica_state


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_live(url: str, process: subprocess.Popen[Any]) -> None:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Gateway exited before liveness became healthy: {process.returncode}")
        try:
            if httpx.get(f"{url}/live", timeout=0.5, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise TimeoutError("Gateway replicas did not become live within 25 seconds")


def fixture_config(directory: Path, suffix: str) -> Path:
    raw = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    raw["clients"] = [
        {
            "client_id": "demo-client",
            "api_key": "demo-key",
            "rate_limit": {"requests_per_minute": 1000},
            "token_budget": {"period": "daily", "max_tokens": 100_000},
        },
        {
            "client_id": f"redis-rate-{suffix}",
            "api_key": f"redis-rate-key-{suffix}",
            "rate_limit": {"requests_per_minute": 10},
            "token_budget": {"period": "daily", "max_tokens": 100_000},
        },
        {
            "client_id": f"redis-cache-{suffix}",
            "api_key": f"redis-cache-key-{suffix}",
            "rate_limit": {"requests_per_minute": 100},
            "token_budget": {"period": "daily", "max_tokens": 100_000},
        },
        {
            "client_id": "replica-budget",
            "api_key": "replica-budget-key",
            "rate_limit": {"requests_per_minute": 100},
            "token_budget": {"period": "daily", "max_tokens": 100_000},
        },
    ]
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


async def run(
    gateway_a: str, gateway_b: str, redis_url: str, database_url: str, suffix: str
) -> dict[str, object]:
    replica = await probe_replica_state(
        gateway_a,
        gateway_b,
        rate_api_key=f"redis-rate-key-{suffix}",
        cache_api_key=f"redis-cache-key-{suffix}",
        cache_nonce=suffix,
    )
    singleflight = await probe_singleflight(gateway_a, gateway_b, redis_url)
    request_ids = [f"wave3-budget-race-{uuid.uuid4().hex}" for _ in range(2)]
    payload = {
        "profile": "fast-chat",
        "messages": [{"role": "user", "content": "shared PostgreSQL budget race"}],
        "max_tokens": 60_000,
    }
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    f"{url}/v1/chat",
                    headers={
                        "Authorization": "Bearer replica-budget-key",
                        "x-request-id": request_id,
                    },
                    json={
                        **payload,
                        "messages": [
                            {"role": "user", "content": f"shared PostgreSQL budget race {index}"}
                        ],
                    },
                )
                for index, (url, request_id) in enumerate(
                    zip((gateway_a, gateway_b), request_ids, strict=True)
                )
            )
        )
    statuses = [response.status_code for response in responses]
    with connect(database_url) as connection:
        reservations = connection.execute(
            "SELECT reservation_id,state FROM token_budget_reservations "
            "WHERE client_id='replica-budget' AND reservation_id LIKE ANY(%s) "
            "ORDER BY reservation_id",
            ([f"{request_id}:%" for request_id in request_ids],),
        ).fetchall()
        budget = connection.execute(
            "SELECT COALESCE(u.tokens_used,0) AS used, "
            "COALESCE(sum(r.tokens_reserved) FILTER (WHERE r.state='reserved'),0) AS reserved "
            "FROM clients c LEFT JOIN token_budget_usage u ON u.client_id=c.client_id "
            "LEFT JOIN token_budget_reservations r ON r.client_id=c.client_id "
            "WHERE c.client_id='replica-budget' GROUP BY u.tokens_used"
        ).fetchone()
        audits = connection.execute(
            "SELECT request_id,status,error_code FROM request_logs "
            "WHERE request_id = ANY(%s) ORDER BY request_id",
            (request_ids,),
        ).fetchall()
        attempts = connection.execute(
            "SELECT request_id,provider_id,status FROM provider_attempts "
            "WHERE request_id = ANY(%s) ORDER BY request_id,attempt_order",
            (request_ids,),
        ).fetchall()
    budget_race = {
        "request_statuses": statuses,
        "reservation_states": [dict(row) for row in reservations],
        "used_tokens": int(budget["used"]),
        "reserved_tokens": int(budget["reserved"]),
        "audit_rows": [dict(row) for row in audits],
        "provider_attempt_rows": [dict(row) for row in attempts],
    }
    budget_race["oracle_pass"] = (
        sorted(statuses) == [200, 429]
        and len(audits) == 2
        and budget["used"] + budget["reserved"] <= 100_000
        and len(reservations) == 1
        and reservations[0]["state"] == "settled"
        and reservations[0]["reservation_id"].startswith(
            next(row["request_id"] for row in audits if row["status"] == "success") + ":"
        )
        and next(row for row in audits if row["status"] == "error")["error_code"]
        == "token_budget_exceeded"
        and len(attempts) == 1
    )
    return {
        "global_rate_limit_cache": replica,
        "distributed_singleflight_and_lease": singleflight,
        "postgres_shared_budget_race": budget_race,
        "oracle_pass": (
            replica["oracle_pass"] and singleflight["oracle_pass"] and budget_race["oracle_pass"]
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="gateway-wave3-redis-") as temporary:
        directory = Path(temporary)
        suffix = uuid.uuid4().hex
        config_path = fixture_config(directory, suffix)
        environment = os.environ.copy()
        environment.update(
            {
                "GW_CONFIG_PATH": str(config_path),
                "GW_DATABASE_URL": args.database_url,
                "GW_REDIS_URL": args.redis_url,
                "GW_CACHE_BACKEND": "redis",
                "GW_LOG_LEVEL": "WARNING",
            }
        )
        urls = [f"http://127.0.0.1:{free_port()}" for _ in range(2)]
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    url.rsplit(":", 1)[1],
                    "--log-level",
                    "warning",
                    "--no-access-log",
                ],
                cwd=ROOT,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for url in urls
        ]
        try:
            for url, process in zip(urls, processes, strict=True):
                wait_live(url, process)
            result = asyncio.run(
                run(urls[0], urls[1], args.redis_url, args.database_url, suffix)
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["oracle_pass"] else 1
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
