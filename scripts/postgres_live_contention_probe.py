"""Capture PostgreSQL live wait-state evidence while synthetic TCP traffic runs."""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg

ACTIVITY_SQL = """
SELECT clock_timestamp() AS sampled_at, pid, application_name, state,
       wait_event_type, wait_event,
       round(extract(epoch FROM clock_timestamp() - query_start)::numeric * 1000, 3)
           AS query_age_ms,
       round(extract(epoch FROM clock_timestamp() - xact_start)::numeric * 1000, 3)
           AS transaction_age_ms,
       pg_blocking_pids(pid) AS blocking_pids,
       md5(coalesce(query, '')) AS query_fingerprint
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
  AND backend_type = 'client backend'
  AND state <> 'idle'
ORDER BY pid
"""


def db_snapshot(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    activity = conn.execute(ACTIVITY_SQL).fetchall()
    locks = conn.execute(
        "SELECT locktype, mode, granted, count(*) AS count "
        "FROM pg_locks GROUP BY locktype, mode, granted ORDER BY locktype, mode, granted"
    ).fetchall()
    database = conn.execute(
        "SELECT deadlocks, conflicts, xact_commit, xact_rollback, temp_bytes "
        "FROM pg_stat_database WHERE datname = current_database()"
    ).fetchone()
    return {"sampled_at": datetime.now(UTC).isoformat(), "activity": activity,
            "locks": locks, "database": database}


def request_one(
    client: httpx.Client, base_url: str, api_keys: list[str], run_id: str,
    sequence: int, requests_total: int, cache_ratio: float, cache_key_count: int
) -> dict[str, Any]:
    request_id = f"ph-{run_id}-{sequence:05d}"
    content = (f"synthetic-hot-{sequence % cache_key_count}"
               if sequence / requests_total < cache_ratio else f"synthetic-{request_id}")
    started = time.monotonic()
    try:
        response = client.post(
            f"{base_url.rstrip('/')}/v1/chat",
            headers={"Authorization": f"Bearer {api_keys[sequence % len(api_keys)]}",
                     "x-request-id": request_id},
            json={"profile": "fast-chat", "max_tokens": 16,
                  "messages": [{"role": "user", "content": content}]},
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        error = body.get("error", {}) if isinstance(body, dict) else {}
        return {"request_id": request_id, "status": response.status_code,
                "error_code": error.get("code"), "duration_ms": round(
                    (time.monotonic() - started) * 1000, 3)}
    except httpx.HTTPError as exc:
        return {"request_id": request_id, "status": 0,
                "error_code": type(exc).__name__, "duration_ms": round(
                    (time.monotonic() - started) * 1000, 3)}


def persisted_snapshot(database_url: str, request_ids: list[str]) -> dict[str, Any]:
    patterns = [f"{request_id}:%" for request_id in request_ids]
    with psycopg.connect(database_url, connect_timeout=2, autocommit=True,
                         options="-c statement_timeout=1500") as conn:
        logs = conn.execute(
            "SELECT request_id, status, status_code, error_code, cache_hit, input_tokens, output_tokens "
            "FROM request_logs WHERE request_id = ANY(%s) ORDER BY request_id",
            (request_ids,),
        ).fetchall()
        reservations = conn.execute(
            "SELECT reservation_id, state, tokens_reserved FROM token_budget_reservations "
            "WHERE reservation_id LIKE ANY(%s) ORDER BY reservation_id", (patterns,)
        ).fetchall()
        receipts = conn.execute(
            "SELECT request_id, operation, tokens, budget_after FROM stream_finalizations "
            "WHERE request_id = ANY(%s) ORDER BY request_id", (request_ids,)
        ).fetchall()
        attempts = conn.execute(
            "SELECT request_id, attempt_order, status, error_code FROM provider_attempts "
            "WHERE request_id = ANY(%s) ORDER BY request_id, attempt_order", (request_ids,)
        ).fetchall()
        totals = conn.execute(
            "SELECT state, count(*) FROM token_budget_reservations GROUP BY state ORDER BY state"
        ).fetchall()
        usage = conn.execute(
            "SELECT client_id, period, tokens_used FROM token_budget_usage ORDER BY client_id, period"
        ).fetchall()
    return {"request_logs": logs, "reservations": reservations, "receipts": receipts,
            "provider_attempts": attempts, "reservation_totals": totals, "usage": usage}


def monitor_database(database_url: str, interval: float, stop: threading.Event,
                     samples: list[dict[str, Any]]) -> None:
    try:
        with psycopg.connect(database_url, connect_timeout=2, autocommit=True,
                             options="-c statement_timeout=1500") as conn:
            while not stop.is_set():
                started = time.monotonic()
                try:
                    samples.append(db_snapshot(conn))
                except psycopg.Error as exc:
                    samples.append({"sampled_at": datetime.now(UTC).isoformat(),
                                    "monitor_error": type(exc).__name__,
                                    "sqlstate": exc.sqlstate})
                stop.wait(max(0.01, interval - (time.monotonic() - started)))
    except psycopg.Error as exc:
        samples.append({"sampled_at": datetime.now(UTC).isoformat(),
                        "monitor_start_error": type(exc).__name__, "sqlstate": exc.sqlstate})


def hold_budget_lock(database_url: str, client_id: str, period: str, duration_ms: int,
                     acquired: threading.Event, release: threading.Event) -> None:
    """Inject a bounded same-client reservation lock hold in the disposable DB."""
    with psycopg.connect(database_url, connect_timeout=2) as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                     (f"{client_id}:{period}",))
        acquired.set()
        release.wait(duration_ms / 1000)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--database-url", default=os.getenv("GW_DIAGNOSTIC_DATABASE_URL"))
    parser.add_argument("--requests", type=int, default=64)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--api-keys", default=os.getenv("GW_DIAGNOSTIC_API_KEYS", "demo-key"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sample-interval-ms", type=float, default=100)
    parser.add_argument("--spread-ms", type=float, default=0,
                        help="Delay between request submissions for low-rate probes")
    parser.add_argument("--cache-ratio", type=float, default=0)
    parser.add_argument("--cache-key-count", type=int, default=4)
    parser.add_argument("--hold-client-id")
    parser.add_argument("--hold-period")
    parser.add_argument("--hold-lock-ms", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (not re.fullmatch(r"[a-zA-Z0-9-]{1,32}", args.run_id)
            or args.requests < 1 or args.concurrency < 1 or args.sample_interval_ms <= 0
            or args.spread_ms < 0):
        parser.error("invalid run id, request/concurrency count, or sampling interval")
    if not 0 <= args.cache_ratio <= 1 or args.cache_key_count < 1:
        parser.error("cache ratio must be within [0, 1] and cache key count positive")
    if bool(args.hold_client_id) != bool(args.hold_period) or not 0 <= args.hold_lock_ms <= 10000:
        parser.error("lock injection needs both client/period and a bounded 0-10000ms duration")
    if args.hold_lock_ms and not args.hold_client_id:
        parser.error("lock duration requires a client id and period")
    api_keys = [key.strip() for key in args.api_keys.split(",") if key.strip()]
    if not api_keys or not args.database_url:
        parser.error("a database URL and at least one synthetic client key are required")

    samples: list[dict[str, Any]] = []
    stop = threading.Event()
    release_lock = threading.Event()
    lock_acquired = threading.Event()
    lock_thread: threading.Thread | None = None
    if args.hold_lock_ms:
        lock_thread = threading.Thread(
            target=hold_budget_lock,
            args=(args.database_url, args.hold_client_id, args.hold_period,
                  args.hold_lock_ms, lock_acquired, release_lock),
            daemon=True,
        )
        lock_thread.start()
        if not lock_acquired.wait(5):
            release_lock.set()
            parser.error("timed out acquiring the disposable advisory lock")
    monitor = threading.Thread(target=monitor_database,
                               args=(args.database_url, args.sample_interval_ms / 1000,
                                     stop, samples),
                               daemon=True)
    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=httpx.Timeout(15, connect=2), trust_env=False,
                      limits=httpx.Limits(max_connections=max(20, args.concurrency * 2))) as client:
        monitor.start()
        try:
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = []
                for sequence in range(args.requests):
                    futures.append(pool.submit(request_one, client, args.url, api_keys,
                                               args.run_id, sequence, args.requests,
                                               args.cache_ratio, args.cache_key_count))
                    if args.spread_ms:
                        time.sleep(args.spread_ms / 1000)
                for future in as_completed(futures):
                    results.append(future.result())
        finally:
            stop.set()
            monitor.join(timeout=5)
            release_lock.set()
            if lock_thread is not None:
                lock_thread.join(timeout=5)
    results.sort(key=lambda result: result["request_id"])
    request_ids = [result["request_id"] for result in results]
    persisted: dict[str, Any]
    try:
        persisted = persisted_snapshot(args.database_url, request_ids)
    except psycopg.Error as exc:
        persisted = {"snapshot_error": type(exc).__name__, "sqlstate": exc.sqlstate}
    counts: dict[str, int] = {}
    for result in results:
        key = f"{result['status']}:{result['error_code'] or 'none'}"
        counts[key] = counts.get(key, 0) + 1
    report = {"run_id": args.run_id, "started_at": datetime.now(UTC).isoformat(),
              "requests": args.requests, "concurrency": args.concurrency,
              "client_count": len(api_keys), "spread_ms": args.spread_ms,
              "cache_ratio_target": args.cache_ratio,
              "advisory_lock_injection": bool(args.hold_lock_ms),
              "advisory_lock_hold_ms": args.hold_lock_ms,
              "result_counts": counts, "request_results": results,
              "live_database_samples": samples, "persisted_state": persisted}
    serialized = json.dumps(report, indent=2, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
