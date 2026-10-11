"""Hold a disposable PostgreSQL reservation row during an SSE finalization."""

from __future__ import annotations

import argparse
import json
import os
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg


def block_reservation(
    database_url: str,
    request_id: str,
    hold_ms: int,
    acquired: threading.Event,
    release: threading.Event,
) -> None:
    with psycopg.connect(database_url, connect_timeout=2) as conn, conn.transaction():
        row = conn.execute(
            "SELECT reservation_id FROM token_budget_reservations "
            "WHERE reservation_id LIKE %s FOR UPDATE",
            (f"{request_id}:%",),
        ).fetchone()
        if row is None:
            raise RuntimeError("stream reservation was not persisted before first token")
        acquired.set()
        release.wait(hold_ms / 1000)


def snapshot(database_url: str, request_id: str) -> dict[str, Any]:
    with psycopg.connect(database_url, connect_timeout=2, autocommit=True) as conn:
        log = conn.execute(
            "SELECT status,status_code,error_code,input_tokens,output_tokens,budget_after "
            "FROM request_logs WHERE request_id=%s",
            (request_id,),
        ).fetchall()
        reservation = conn.execute(
            "SELECT reservation_id,state,tokens_reserved FROM token_budget_reservations "
            "WHERE reservation_id LIKE %s",
            (f"{request_id}:%",),
        ).fetchall()
        receipt = conn.execute(
            "SELECT reservation_id,operation,tokens,budget_after FROM stream_finalizations "
            "WHERE request_id=%s",
            (request_id,),
        ).fetchall()
        attempts = conn.execute(
            "SELECT attempt_order,status,error_code FROM provider_attempts "
            "WHERE request_id=%s ORDER BY attempt_order",
            (request_id,),
        ).fetchall()
    return {"request_log": log, "reservation": reservation, "receipt": receipt,
            "provider_attempts": attempts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("GW_DIAGNOSTIC_DATABASE_URL"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", default="demo-key")
    parser.add_argument("--hold-ms", type=int, default=2800)
    args = parser.parse_args()
    if not args.database_url or not 1500 <= args.hold_ms <= 6000:
        parser.error("database URL and a bounded 1500-6000ms hold are required")
    request_id = f"stream-finalize-lock-{uuid.uuid4().hex[:12]}"
    acquired = threading.Event()
    release = threading.Event()
    blocker: threading.Thread | None = None
    lines: list[str] = []
    with httpx.Client(timeout=15, trust_env=False) as client, client.stream(
        "POST", f"{args.base_url.rstrip('/')}/v1/chat",
        headers={"Authorization": f"Bearer {args.api_key}", "x-request-id": request_id},
        json={"profile": "fast-chat", "stream": True, "max_tokens": 16,
              "messages": [{"role": "user", "content": f"synthetic {request_id}"}]},
    ) as response:
        status = response.status_code
        content_type = response.headers.get("content-type")
        for line in response.iter_lines():
            lines.append(line)
            if line == "event: message" and blocker is None:
                blocker = threading.Thread(
                    target=block_reservation,
                    args=(args.database_url, request_id, args.hold_ms, acquired, release),
                    daemon=True,
                )
                blocker.start()
                if not acquired.wait(3):
                    release.set()
                    raise RuntimeError("timed out locking stream reservation")
    if blocker is not None:
        release.set()
        blocker.join(timeout=5)
    persisted = snapshot(args.database_url, request_id)
    report = {
        "started_utc": datetime.now(UTC).isoformat(), "request_id": request_id,
        "hold_ms": args.hold_ms, "status": status, "content_type": content_type,
        "sse_lines": lines, "persisted": persisted,
    }
    print(json.dumps(report, indent=2, default=str))
    # This probe is diagnostic: a failure or state combination is evidence to
    # review, not an assertion that accounting behavior is acceptable.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
