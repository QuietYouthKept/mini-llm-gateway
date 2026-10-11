"""Exercise stream admission under a real PostgreSQL advisory-lock timeout.

This probe is intentionally limited to a disposable PostgreSQL/Gateway pair and
synthetic requests. It records HTTP/SSE observations and durable accounting rows
without exporting credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg


def hold_budget_lock(
    database_url: str,
    client_id: str,
    period: str,
    hold_ms: int,
    acquired: threading.Event,
    release: threading.Event,
) -> None:
    with psycopg.connect(database_url, connect_timeout=2) as conn, conn.transaction():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{client_id}:{period}",),
        )
        acquired.set()
        release.wait(hold_ms / 1000)


def request_stream(base_url: str, api_key: str, request_id: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with httpx.Client(timeout=15, trust_env=False) as client, client.stream(
            "POST",
            f"{base_url.rstrip('/')}/v1/chat",
            headers={
                "Authorization": f"Bearer {api_key}",
                "x-request-id": request_id,
            },
            json={
                "profile": "fast-chat",
                "stream": True,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": f"synthetic {request_id}"}],
            },
        ) as response:
            body = "".join(response.iter_text())
            try:
                parsed = json.loads(body) if response.status_code >= 400 else None
            except json.JSONDecodeError:
                parsed = None
            return {
                "request_id": request_id,
                "status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "body": parsed if parsed is not None else body,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
            }
    except httpx.HTTPError as exc:
        return {
            "request_id": request_id,
            "status": 0,
            "transport_error": type(exc).__name__,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        }


def persisted_snapshot(database_url: str, request_ids: list[str]) -> dict[str, Any]:
    prefixes = [f"{request_id}:%" for request_id in request_ids]
    with psycopg.connect(
        database_url,
        connect_timeout=2,
        autocommit=True,
        options="-c statement_timeout=2000",
    ) as conn:
        logs = conn.execute(
            "SELECT request_id,status,status_code,error_code,input_tokens,output_tokens "
            "FROM request_logs WHERE request_id=ANY(%s) ORDER BY request_id",
            (request_ids,),
        ).fetchall()
        reservations = conn.execute(
            "SELECT reservation_id,state,tokens_reserved FROM token_budget_reservations "
            "WHERE reservation_id LIKE ANY(%s) ORDER BY reservation_id",
            (prefixes,),
        ).fetchall()
        receipts = conn.execute(
            "SELECT reservation_id,request_id,operation,tokens,budget_after "
            "FROM stream_finalizations WHERE request_id=ANY(%s) ORDER BY request_id",
            (request_ids,),
        ).fetchall()
        attempts = conn.execute(
            "SELECT request_id,attempt_order,status,error_code FROM provider_attempts "
            "WHERE request_id=ANY(%s) ORDER BY request_id,attempt_order",
            (request_ids,),
        ).fetchall()
        usage = conn.execute(
            "SELECT client_id,period,tokens_used FROM token_budget_usage "
            "WHERE client_id IN ('demo-client','burst-client') ORDER BY client_id,period"
        ).fetchall()
    return {
        "request_logs": logs,
        "reservations": reservations,
        "receipts": receipts,
        "provider_attempts": attempts,
        "usage": usage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("GW_DIAGNOSTIC_DATABASE_URL"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--demo-api-key", default="demo-key")
    parser.add_argument("--control-api-key", default="burst-key")
    parser.add_argument("--client-id", default="demo-client")
    parser.add_argument("--control-client-id", default="burst-client")
    parser.add_argument("--hold-ms", type=int, default=4500)
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or GW_DIAGNOSTIC_DATABASE_URL is required")
    if not 1000 <= args.hold_ms <= 8000:
        parser.error("hold-ms must be bounded between 1000 and 8000")

    with psycopg.connect(args.database_url, connect_timeout=2, autocommit=True) as conn:
        client = conn.execute(
            "SELECT budget_period FROM clients WHERE client_id=%s", (args.client_id,)
        ).fetchone()
        if client is None:
            parser.error("configured synthetic client was not found")
        period_type = client[0]
    period_format = {"daily": "%Y-%m-%d", "monthly": "%Y-%m", "yearly": "%Y"}.get(
        period_type, "%Y-%m-%d"
    )
    period = datetime.now().strftime(period_format)
    run_id = uuid.uuid4().hex[:12]
    request_ids = [f"stream-lock-{run_id}-same", f"stream-lock-{run_id}-control"]
    acquired = threading.Event()
    release = threading.Event()
    lock_thread = threading.Thread(
        target=hold_budget_lock,
        args=(args.database_url, args.client_id, period, args.hold_ms, acquired, release),
        daemon=True,
    )
    lock_thread.start()
    if not acquired.wait(5):
        release.set()
        parser.error("did not acquire bounded advisory lock")
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            same = pool.submit(request_stream, args.base_url, args.demo_api_key, request_ids[0])
            control = pool.submit(
                request_stream, args.base_url, args.control_api_key, request_ids[1]
            )
            results = [same.result(), control.result()]
    finally:
        release.set()
        lock_thread.join(timeout=5)
    snapshot = persisted_snapshot(args.database_url, request_ids)
    report = {
        "started_utc": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "client_ids": [args.client_id, args.control_client_id],
        "request_ids": request_ids,
        "period_type": period_type,
        "period_key": period,
        "lock_hold_ms": args.hold_ms,
        "requests": results,
        "persisted": snapshot,
    }
    print(json.dumps(report, indent=2, default=str))
    same_request = results[0]
    same_code = None
    if isinstance(same_request.get("body"), dict):
        error = same_request["body"].get("error", {})
        same_code = error.get("code") if isinstance(error, dict) else None
    control_ok = results[1].get("status") == 200 and "event: done" in str(results[1].get("body"))
    failed = (
        same_request.get("status") != 503
        or same_code != "database_lock_timeout"
        or not control_ok
        or len(snapshot["request_logs"]) != 2
        or len(snapshot["reservations"]) != 1
        or len(snapshot["receipts"]) != 1
        or len(snapshot["provider_attempts"]) != 1
    )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
