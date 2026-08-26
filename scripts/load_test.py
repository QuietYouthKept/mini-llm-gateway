"""Small deterministic HTTP load harness for gateway evidence, not correctness proof."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections import Counter
from pathlib import Path
from statistics import mean

import httpx

try:
    import psutil
except ImportError:  # pragma: no cover - optional load-evidence dependency
    psutil = None


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, math.ceil(percentile_value * len(ordered)) - 1)
    return ordered[index]


def payload_for(scenario: str, index: int) -> dict:
    profile = "fast-chat"
    if scenario == "provider-timeout":
        profile = "timeout-chat"
    elif scenario == "provider-latency":
        profile = "latency-chat"
    elif scenario == "retry-storm":
        profile = "fallback-chat"

    if scenario == "cache-heavy":
        content = f"cache prompt {index % 4}"
    elif scenario in {"long-prompt", "long-context"}:
        content = "x" * 3500 + str(index % 4)
    else:
        content = f"unique prompt {scenario} {index}"
    return {
        "profile": profile,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 64,
    }


async def run(args: argparse.Namespace) -> dict:
    semaphore = asyncio.Semaphore(args.concurrency)
    latencies: list[float] = []
    statuses: list[int] = []
    attempts = 0
    retries = 0
    cache_hits = 0
    fallbacks = 0
    error_codes: list[str] = []
    headers = {"Authorization": f"Bearer {args.api_key}"}
    process = psutil.Process(args.process_pid) if psutil and args.process_pid else None

    def process_usage() -> tuple[float, int]:
        if process is None:
            return 0.0, 0
        cpu = 0.0
        rss = 0
        for item in [process, *process.children(recursive=True)]:
            try:
                times = item.cpu_times()
                cpu += times.user + times.system
                rss += item.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return cpu, rss

    cpu_before, rss_before = process_usage()

    # Local evidence must not be routed through a workstation HTTP proxy.
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        async def one(index: int) -> None:
            nonlocal attempts, retries, cache_hits, fallbacks
            if args.scenario == "ramp":
                await asyncio.sleep(index * args.ramp_interval_ms / 1000.0)
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.post(
                        args.url.rstrip("/") + "/v1/chat",
                        json=payload_for(args.scenario, index),
                        headers=headers,
                    )
                except httpx.HTTPError as exc:
                    latencies.append((time.perf_counter() - started) * 1000.0)
                    statuses.append(0)
                    error_codes.append(type(exc).__name__)
                    return
                latencies.append((time.perf_counter() - started) * 1000.0)
                statuses.append(response.status_code)
                if response.headers.get("content-type", "").startswith("application/json"):
                    body = response.json()
                    response_attempts = body.get("attempts", [])
                    attempts += len(response_attempts)
                    retries += sum(int(attempt.get("retry_index", 0) > 0) for attempt in response_attempts)
                    cache_hits += int(bool(body.get("cache_hit")))
                    fallbacks += int(bool(body.get("fallback_used")))
                    if response.status_code not in args.expected_status:
                        error_codes.append((body.get("error") or {}).get("code", "http_error"))

        started = time.perf_counter()
        await asyncio.gather(*(one(index) for index in range(args.requests)))
        elapsed = time.perf_counter() - started

    successes = sum(status in args.expected_status for status in statuses)
    cpu_after, rss_after = process_usage()
    unexpected = len(statuses) - successes
    error_counts = Counter(error_codes)
    return {
        "scenario": args.scenario,
        "requests": len(statuses),
        "concurrency": args.concurrency,
        "elapsed_seconds": round(elapsed, 4),
        "rps": round(len(statuses) / elapsed, 2) if elapsed else 0.0,
        "throughput_requests_per_second": round(len(statuses) / elapsed, 2) if elapsed else 0.0,
        "latency_ms": {
            "mean": round(mean(latencies), 2) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
            "p99": round(percentile(latencies, 0.99), 2),
        },
        "success": successes,
        "http_errors": unexpected,
        "error_rate": round(unexpected / len(statuses), 4) if statuses else 0.0,
        "provider_attempts_per_request": round(attempts / len(statuses), 3) if statuses else 0.0,
        "retry_amplification_ratio": round(retries / len(statuses), 3) if statuses else 0.0,
        "cache_hit_ratio": round(cache_hits / len(statuses), 3) if statuses else 0.0,
        "fallback_ratio": round(fallbacks / len(statuses), 3) if statuses else 0.0,
        "budget_reject_count": error_counts["token_budget_exceeded"],
        "rate_limit_reject_count": error_counts["rate_limit_exceeded"],
        "process": {
            "pid": args.process_pid,
            "cpu_seconds": round(cpu_after - cpu_before, 3),
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
            "rss_delta_bytes": rss_after - rss_before,
        },
        "backend_errors": {
            "sqlite": error_counts["internal_error"] if args.state_backend == "sqlite" else 0,
            "postgres": error_counts["internal_error"] if args.state_backend == "postgres" else 0,
            "redis": error_counts["internal_error"] if args.state_backend == "redis" else 0,
        },
        "error_codes": dict(error_counts),
        "status_counts": {str(code): statuses.count(code) for code in sorted(set(statuses))},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="demo-key")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--ramp-interval-ms", type=float, default=10.0)
    parser.add_argument("--process-pid", type=int, default=0)
    parser.add_argument("--state-backend", choices=("sqlite", "postgres", "redis"), default="sqlite")
    parser.add_argument("--expected-status", type=int, action="append", default=None)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--scenario",
        choices=(
            "constant",
            "ramp",
            "spike",
            "soak",
            "cache-heavy",
            "cache-miss",
            "long-prompt",
            "long-context",
            "provider-latency",
            "provider-timeout",
            "retry-storm",
        ),
        default="constant",
    )
    args = parser.parse_args()
    if args.requests <= 0 or args.concurrency <= 0:
        parser.error("requests and concurrency must be positive")
    args.expected_status = set(args.expected_status or [200])
    result = asyncio.run(run(args))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 1 if result["error_rate"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
