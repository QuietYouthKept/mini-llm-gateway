"""Run a reproducible, privacy-safe gateway experiment.

The harness is deliberately an HTTP client: it works against the deterministic
stub setup and against a separately configured real provider.  It never writes
the API key, prompt text, or completion text into the evidence directory.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * p) - 1)]


def sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def git_worktree_provenance() -> dict[str, Any]:
    """Identify uncommitted code without copying any source into evidence."""
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        )
        diff = subprocess.check_output(
            ["git", "diff", "--binary", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return {"dirty": None, "diff_sha256": None}
    return {
        "dirty": bool(status.strip()),
        "diff_sha256": hashlib.sha256(diff).hexdigest() if diff else None,
    }


def parse_tokens(value: str) -> list[int]:
    values = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not values or any(item <= 0 for item in values):
        raise argparse.ArgumentTypeError("token distributions must contain positive integers")
    return values


@dataclass(frozen=True)
class Observation:
    sequence: int
    started_at: str
    request_id: str | None
    status_code: int
    latency_ms: float
    client_queue_wait_ms: float
    provider: str | None
    provider_duration_ms: int
    gateway_overhead_ms: float
    provider_attempts: int
    provider_request_ids: list[str]
    retry_count: int
    cache_hit: bool
    estimated_cost_usd: float
    error_code: str | None
    input_tokens_target: int
    output_tokens_target: int
    ttft_ms: float | None = None
    chunk_count: int = 0
    inter_chunk_p95_ms: float = 0.0
    disconnected: bool = False
    audit_status: str | None = None
    budget_after: int | None = None
    usage_source: str | None = None


def sanitized_payload(
    profile: str,
    input_tokens: int,
    output_tokens: int,
    sequence: int,
    workload_label: str,
) -> dict[str, Any]:
    """Create a deterministic prompt without storing its contents in evidence."""
    # The token estimator in the reference config uses four characters per token.
    prefix = f"benchmark-{workload_label}-{sequence} "
    content = prefix + "x" * max(0, input_tokens * 4 - len(prefix))
    return {
        "profile": profile,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": output_tokens,
    }


async def consume_sse(
    client: httpx.AsyncClient,
    args: argparse.Namespace,
    payload: dict[str, Any],
    started: float,
) -> tuple[int, dict[str, Any], float | None, int, float, bool]:
    """Consume a gateway stream without recording prompt or completion content."""
    payload = dict(payload)
    payload["stream"] = True
    first_chunk_at: float | None = None
    previous_chunk_at: float | None = None
    gaps: list[float] = []
    chunks = 0
    disconnected = False
    last_event = ""
    async with client.stream(
        "POST",
        args.url.rstrip("/") + "/v1/chat",
        headers={"Authorization": f"Bearer {args.api_key}"},
        json=payload,
    ) as response:
        event = "message"
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
                continue
            if not line.startswith("data:"):
                continue
            last_event = event
            if event != "message":
                continue
            now = time.monotonic()
            if first_chunk_at is None:
                first_chunk_at = now
            if previous_chunk_at is not None:
                gaps.append((now - previous_chunk_at) * 1000.0)
            previous_chunk_at = now
            chunks += 1
            if args.disconnect_after_chunks is not None and chunks >= args.disconnect_after_chunks:
                disconnected = True
                break
    return (
        response.status_code,
        {"request_id": response.headers.get("x-request-id"), "event": last_event},
        (first_chunk_at - started) * 1000.0 if first_chunk_at else None,
        chunks,
        percentile(gaps, 0.95),
        disconnected,
    )


async def run_load(args: argparse.Namespace, *, sequence_start: int = 0) -> list[Observation]:
    semaphore = asyncio.Semaphore(args.concurrency)
    randomizer = random.Random(args.seed)
    started = time.monotonic()
    next_sequence = sequence_start
    scheduled = 0
    observations: list[Observation] = []
    lock = asyncio.Lock()

    async with httpx.AsyncClient(timeout=args.timeout_seconds, trust_env=False) as client:

        async def one(sequence: int) -> None:
            if args.shape == "ramp":
                await asyncio.sleep(sequence * args.ramp_interval_ms / 1000.0)
            elif args.shape == "spike" and sequence < args.concurrency:
                # First concurrency-sized wave starts together; subsequent work is normal.
                await asyncio.sleep(0)
            queued = time.monotonic()
            async with semaphore:
                queue_wait_ms = (time.monotonic() - queued) * 1000.0
                input_tokens = randomizer.choice(args.input_tokens)
                output_tokens = randomizer.choice(args.output_tokens)
                if args.cache_ratio and randomizer.random() < args.cache_ratio:
                    # Stable sequence gives an exact-cache candidate without leaking data.
                    payload_sequence = sequence % args.cache_key_count
                else:
                    payload_sequence = sequence
                payload = sanitized_payload(
                    args.profile,
                    input_tokens,
                    output_tokens,
                    payload_sequence,
                    args.workload_label,
                )
                wall_started = datetime.now(UTC).isoformat()
                call_started = time.monotonic()
                try:
                    if args.stream:
                        (
                            status_code,
                            body,
                            ttft_ms,
                            chunk_count,
                            gap_p95,
                            disconnected,
                        ) = await consume_sse(client, args, payload, call_started)
                        response_headers_request_id = body.get("request_id")
                        audit_body: dict[str, Any] = {}
                        if response_headers_request_id:
                            audit = await client.get(
                                args.url.rstrip("/")
                                + f"/v1/requests/{response_headers_request_id}",
                                headers={"Authorization": f"Bearer {args.api_key}"},
                            )
                            if audit.status_code == 200:
                                audit_body = audit.json()
                        body = audit_body or body
                        attempts = body.get("attempts", []) if isinstance(body, dict) else []
                        error = body.get("error") if isinstance(body, dict) else None
                        if status_code >= 400 and error is None:
                            error = {"code": "stream_http_error"}
                    else:
                        response = await client.post(
                            args.url.rstrip("/") + "/v1/chat",
                            headers={"Authorization": f"Bearer {args.api_key}"},
                            json=payload,
                        )
                        status_code = response.status_code
                        body = (
                            response.json()
                            if "json" in response.headers.get("content-type", "")
                            else {}
                        )
                        response_headers_request_id = response.headers.get("x-request-id")
                        attempts = body.get("attempts", []) if isinstance(body, dict) else []
                        error = body.get("error") if isinstance(body, dict) else None
                        ttft_ms, chunk_count, gap_p95, disconnected = None, 0, 0.0, False
                    latency_ms = (time.monotonic() - call_started) * 1000.0
                    provider_duration_ms = sum(
                        int(item.get("latency_ms", 0) or 0) for item in attempts
                    )
                    item = Observation(
                        sequence=sequence,
                        started_at=wall_started,
                        request_id=response_headers_request_id or body.get("request_id"),
                        status_code=status_code,
                        latency_ms=round(latency_ms, 3),
                        client_queue_wait_ms=round(queue_wait_ms, 3),
                        provider=(
                            body.get("provider") or body.get("selected_provider")
                            if isinstance(body, dict)
                            else None
                        ),
                        provider_duration_ms=provider_duration_ms,
                        gateway_overhead_ms=round(max(0.0, latency_ms - provider_duration_ms), 3),
                        provider_attempts=len(attempts),
                        provider_request_ids=[
                            str(item["provider_request_id"])
                            for item in attempts
                            if item.get("provider_request_id")
                        ],
                        retry_count=sum(int(item.get("retry_index", 0) > 0) for item in attempts),
                        cache_hit=bool(body.get("cache_hit")) if isinstance(body, dict) else False,
                        estimated_cost_usd=float(body.get("estimated_cost_usd", 0.0) or 0.0),
                        error_code=(error or {}).get("code") if isinstance(error, dict) else None,
                        input_tokens_target=input_tokens,
                        output_tokens_target=output_tokens,
                        ttft_ms=round(ttft_ms, 3) if ttft_ms is not None else None,
                        chunk_count=chunk_count,
                        inter_chunk_p95_ms=round(gap_p95, 3),
                        disconnected=disconnected,
                        audit_status=body.get("status") if isinstance(body, dict) else None,
                        budget_after=body.get("budget_after") if isinstance(body, dict) else None,
                        usage_source=body.get("usage_source") if isinstance(body, dict) else None,
                    )
                except (httpx.HTTPError, ValueError) as exc:
                    latency_ms = (time.monotonic() - call_started) * 1000.0
                    item = Observation(
                        sequence=sequence,
                        started_at=wall_started,
                        request_id=None,
                        status_code=0,
                        latency_ms=round(latency_ms, 3),
                        client_queue_wait_ms=round(queue_wait_ms, 3),
                        provider=None,
                        provider_duration_ms=0,
                        gateway_overhead_ms=round(latency_ms, 3),
                        provider_attempts=0,
                        provider_request_ids=[],
                        retry_count=0,
                        cache_hit=False,
                        estimated_cost_usd=0.0,
                        error_code=type(exc).__name__,
                        input_tokens_target=input_tokens,
                        output_tokens_target=output_tokens,
                        disconnected=bool(args.stream and args.disconnect_after_chunks is not None),
                    )
                async with lock:
                    observations.append(item)

        tasks: list[asyncio.Task[None]] = []
        while True:
            if args.duration_seconds is not None:
                if time.monotonic() - started >= args.duration_seconds:
                    break
            elif scheduled >= args.requests:
                break
            tasks.append(asyncio.create_task(one(next_sequence)))
            next_sequence += 1
            scheduled += 1
            # Keep duration mode bounded; scheduling unlimited tasks hides client queueing.
            if len(tasks) >= args.concurrency * 4:
                await asyncio.gather(*tasks)
                tasks.clear()
        if tasks:
            await asyncio.gather(*tasks)
    return sorted(observations, key=lambda item: item.sequence)


def build_manifest(args: argparse.Namespace, run_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": git_commit(),
        "git_worktree": git_worktree_provenance(),
        "config": {
            "path": str(args.config) if args.config else None,
            "sha256": sha256(args.config),
        },
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "machine": platform.machine(),
        },
        "provider": {
            "mode": args.provider_mode,
            "name": args.provider_name,
            "model": args.provider_model,
            "comparison_group": args.provider_mode,
        },
        "workload": {
            "url": args.url,
            "profile": args.profile,
            "concurrency": args.concurrency,
            "requests": args.requests if args.duration_seconds is None else None,
            "duration_seconds": args.duration_seconds,
            "warmup_requests": args.warmup_requests,
            "shape": args.shape,
            "seed": args.seed,
            "input_tokens": args.input_tokens,
            "output_tokens": args.output_tokens,
            "cache_target_ratio": args.cache_ratio,
            "stream": args.stream,
            "disconnect_after_chunks": args.disconnect_after_chunks,
            "workload_label": args.workload_label,
        },
        "privacy": {
            "api_key_recorded": False,
            "prompt_text_recorded": False,
            "completion_text_recorded": False,
        },
    }


def summarize(observations: list[Observation], elapsed_seconds: float) -> dict[str, Any]:
    latencies = [item.latency_ms for item in observations]
    provider = [item.provider_duration_ms for item in observations]
    overhead = [item.gateway_overhead_ms for item in observations]
    successes = [item for item in observations if 200 <= item.status_code < 300]
    attempts = sum(item.provider_attempts for item in observations)
    return {
        "requests": len(observations),
        "successful_requests": len(successes),
        "success_rate": round(len(successes) / len(observations), 6) if observations else 0.0,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "rps": round(len(observations) / elapsed_seconds, 3) if elapsed_seconds else 0.0,
        "status_distribution": dict(Counter(str(item.status_code) for item in observations)),
        "error_distribution": dict(
            Counter(item.error_code for item in observations if item.error_code)
        ),
        "latency_ms": {
            "mean": round(mean(latencies), 3) if latencies else 0.0,
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "provider_duration_ms": {
            "mean": round(mean(provider), 3) if provider else 0.0,
            "p50": percentile(provider, 0.5),
            "p95": percentile(provider, 0.95),
            "p99": percentile(provider, 0.99),
        },
        "gateway_overhead_ms": {
            "mean": round(mean(overhead), 3) if overhead else 0.0,
            "p50": percentile(overhead, 0.5),
            "p95": percentile(overhead, 0.95),
            "p99": percentile(overhead, 0.99),
        },
        "client_queue_wait_ms": {
            "p50": percentile([item.client_queue_wait_ms for item in observations], 0.5),
            "p95": percentile([item.client_queue_wait_ms for item in observations], 0.95),
            "p99": percentile([item.client_queue_wait_ms for item in observations], 0.99),
        },
        "provider_queue_wait": "not implemented: providers are called directly; inspect provider.queue_wait trace spans",
        "provider_calls_per_api_request": round(attempts / len(observations), 4)
        if observations
        else 0.0,
        "retry_amplification_ratio": round(
            sum(item.retry_count for item in observations) / len(observations), 4
        )
        if observations
        else 0.0,
        "cache": {
            "hit_ratio": round(sum(item.cache_hit for item in observations) / len(observations), 4)
            if observations
            else 0.0,
            "estimated_cost_saved_usd": 0.0,
        },
        "estimated_cost_usd": round(sum(item.estimated_cost_usd for item in observations), 8),
        "streaming": {
            "ttft_ms": {
                "p50": percentile(
                    [item.ttft_ms for item in observations if item.ttft_ms is not None], 0.5
                ),
                "p95": percentile(
                    [item.ttft_ms for item in observations if item.ttft_ms is not None], 0.95
                ),
            },
            "chunk_count": sum(item.chunk_count for item in observations),
            "inter_chunk_p95_ms": percentile(
                [item.inter_chunk_p95_ms for item in observations if item.chunk_count > 1], 0.95
            ),
            "client_disconnects": sum(item.disconnected for item in observations),
            "audit_status_distribution": dict(
                Counter(item.audit_status for item in observations if item.audit_status)
            ),
        },
    }


def write_evidence(
    output_dir: Path,
    manifest: dict[str, Any],
    observations: list[Observation],
    summary: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "traces").mkdir()
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    with (output_dir / "requests.jsonl").open("w", encoding="utf-8") as handle:
        for item in observations:
            handle.write(json.dumps(asdict(item), sort_keys=True) + "\n")
    with (output_dir / "latency.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(asdict(observations[0]).keys()) if observations else ["sequence"],
        )
        writer.writeheader()
        writer.writerows(asdict(item) for item in observations)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    report = [
        "# Gateway experiment report",
        "",
        f"- Run: `{manifest['run_id']}`",
        f"- Provider mode: **{manifest['provider']['mode']}** (do not compare directly with the other mode)",
        f"- Provider/model: `{manifest['provider']['name']}` / `{manifest['provider']['model']}`",
        f"- Workload: {manifest['workload']['shape']}, concurrency {manifest['workload']['concurrency']}, seed {manifest['workload']['seed']}",
        f"- Result: {summary['successful_requests']}/{summary['requests']} success; p95 {summary['latency_ms']['p95']} ms; {summary['rps']} RPS.",
        "",
        "## Attribution",
        "",
        f"- Gateway-overhead p95: {summary['gateway_overhead_ms']['p95']} ms (end-to-end latency minus recorded provider attempts).",
        f"- Provider-duration p95: {summary['provider_duration_ms']['p95']} ms.",
        f"- Retry amplification: {summary['retry_amplification_ratio']}; provider calls/API request: {summary['provider_calls_per_api_request']}.",
        "- Provider queueing is not implemented in this gateway; `provider.queue_wait` trace spans make that limitation explicit.",
        "",
        "`requests.jsonl` is sanitized metadata keyed by local request ID and includes upstream provider request IDs when exposed. Prompts, completions, and API keys are intentionally absent.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (output_dir / "traces" / "README.md").write_text(
        "Correlate request_id in requests.jsonl with GET /v1/requests/{request_id} or your OTLP backend.\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=os.getenv("GW_EXPERIMENT_API_KEY", "demo-key"))
    parser.add_argument("--profile", default="fast-chat")
    parser.add_argument("--provider-mode", choices=("stub", "real"), default="stub")
    parser.add_argument("--provider-name", default="unspecified")
    parser.add_argument("--provider-model", default="unspecified")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-root", type=Path, default=ROOT / "evidence" / "load")
    parser.add_argument("--run-id")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--duration-seconds", type=float)
    parser.add_argument("--warmup-requests", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument(
        "--shape", choices=("constant", "ramp", "spike", "soak"), default="constant"
    )
    parser.add_argument("--ramp-interval-ms", type=float, default=20.0)
    parser.add_argument("--input-tokens", type=parse_tokens, default=[8, 32, 128])
    parser.add_argument("--output-tokens", type=parse_tokens, default=[16, 64])
    parser.add_argument("--cache-ratio", type=float, default=0.0)
    parser.add_argument("--cache-key-count", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--stream", action="store_true", help="Request and measure SSE streaming.")
    parser.add_argument(
        "--disconnect-after-chunks",
        type=int,
        help="Close each SSE response after N message chunks to test cancellation propagation.",
    )
    args = parser.parse_args()
    if args.requests <= 0 or args.concurrency <= 0 or args.warmup_requests < 0:
        parser.error("requests/concurrency must be positive and warmup must be non-negative")
    if args.duration_seconds is not None and args.duration_seconds <= 0:
        parser.error("duration-seconds must be positive")
    if not 0 <= args.cache_ratio <= 1 or args.cache_key_count <= 0:
        parser.error("cache-ratio must be within [0, 1] and cache-key-count must be positive")
    if args.disconnect_after_chunks is not None and (
        not args.stream or args.disconnect_after_chunks <= 0
    ):
        parser.error("disconnect-after-chunks requires --stream and a positive value")
    return args


def main() -> int:
    args = parse_args()
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    # A run namespace keeps a live gateway's cache from contaminating an
    # otherwise identical later experiment. It is not prompt content.
    args.workload_label = run_id
    output_dir = args.output_root / run_id
    if output_dir.exists():
        raise SystemExit(f"Evidence directory already exists: {output_dir}")
    if args.warmup_requests:
        warmup = argparse.Namespace(**vars(args))
        warmup.requests, warmup.duration_seconds = args.warmup_requests, None
        # Keep warmup prompts disjoint from recorded requests; otherwise a local
        # exact cache changes the measured cache ratio before the run begins.
        asyncio.run(run_load(warmup, sequence_start=-args.warmup_requests))
    started = time.monotonic()
    observations = asyncio.run(run_load(args))
    summary = summarize(observations, time.monotonic() - started)
    manifest = build_manifest(args, run_id)
    write_evidence(output_dir, manifest, observations, summary)
    print(json.dumps({"output_dir": str(output_dir), "summary": summary}, indent=2))
    return 0 if summary["requests"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
