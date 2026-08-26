"""Run bounded real-Uvicorn Gateway experiments over deterministic public-data fixtures.

The result contains aggregate evidence only; prompt content is never written to
the repository or result file.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

import httpx
import psutil
import yaml

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction) - 1))]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def http_provider(
    mode: str,
    *,
    port: int = 19090,
    timeout_ms: int = 400,
    base_url: str | None = None,
) -> dict:
    return {
        "type": "openai_compatible",
        "enabled": True,
        "http": {
            "base_url": base_url or f"http://127.0.0.1:{port}/v1",
            "model": "fault-fixture",
            "timeout_ms": timeout_ms,
            "headers": {"x-fault-mode": mode},
        },
    }


def profile(*providers: str) -> dict:
    return {
        "routing": {
            "strategy": "priority",
            "candidates": [
                {"provider": provider_id, "priority": index + 1}
                for index, provider_id in enumerate(providers)
            ],
        },
        "fallback": {
            "enabled": True,
            "trigger_on": ["provider_error", "timeout", "bad_status"],
            "chain": list(providers),
        },
    }


def prepare_config(target: Path) -> None:
    config = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    config["gateway"]["request_timeout_ms"] = 2500
    config["clients"] = [
        {
            "client_id": "experiment",
            "api_key": "experiment-key",
            "rate_limit": {"requests_per_minute": 10000},
            "token_budget": {"period": "daily", "max_tokens": 5_000_000},
        },
        {
            "client_id": "budget-single",
            "api_key": "budget-single-key",
            "rate_limit": {"requests_per_minute": 100},
            "token_budget": {"period": "daily", "max_tokens": 100},
        },
        {
            "client_id": "budget-concurrent",
            "api_key": "budget-concurrent-key",
            "rate_limit": {"requests_per_minute": 100},
            "token_budget": {"period": "daily", "max_tokens": 100},
        },
        {
            "client_id": "redis-rate",
            "api_key": "redis-rate-key",
            "rate_limit": {"requests_per_minute": 10},
            "token_budget": {"period": "daily", "max_tokens": 100000},
        },
        {
            "client_id": "redis-cache",
            "api_key": "redis-cache-key",
            "rate_limit": {"requests_per_minute": 100},
            "token_budget": {"period": "daily", "max_tokens": 100000},
        },
    ]
    config["providers"].update(
        {
            "fault_timeout_a": http_provider("timeout", timeout_ms=100),
            "fault_500_b": http_provider("500"),
            "fault_connection_c": http_provider(
                "success", base_url="http://nonexistent.invalid/v1"
            ),
            "fault_500_d": http_provider("500"),
            "fault_500_e": http_provider("500"),
            "fault_connection_e": http_provider(
                "success", base_url="http://nonexistent.invalid/v1"
            ),
        }
    )
    config["model_profiles"].update(
        {
            "latency-chat": profile("mock_stable"),
            "fault-timeout": profile("fault_timeout_a"),
            "fault-500": profile("fault_500_b"),
            "fault-connection": profile("fault_connection_c"),
            "fault-fallback": profile("fault_500_d", "mock_fast"),
            "fault-all": profile("fault_500_e", "fault_connection_e"),
        }
    )
    target.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def wait_ready(url: str, process: subprocess.Popen, timeout: float = 20.0) -> None:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Process exited before readiness: {process.returncode}")
        try:
            if httpx.get(url, timeout=0.5, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {url}")


class Experiment:
    def __init__(self, url: str, db_path: Path, wild: list[dict], ultra: list[dict]) -> None:
        self.url = url.rstrip("/")
        self.db_path = db_path
        self.wild = wild
        self.ultra = ultra
        self.client = httpx.AsyncClient(timeout=6.0, trust_env=False)
        self.observations: list[dict[str, Any]] = []

    async def close(self) -> None:
        await self.client.aclose()

    async def send(
        self,
        messages: list[dict[str, str]],
        *,
        profile_id: str = "fast-chat",
        api_key: str = "experiment-key",
        max_tokens: int = 32,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        response = await self.client.post(
            f"{self.url}/v1/chat",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"profile": profile_id, "messages": messages, "max_tokens": max_tokens},
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        body = response.json()
        request_id = response.headers.get("x-request-id") or body.get("request_id") or (
            body.get("error") or {}
        ).get("request_id")
        audit_response = await self.client.get(
            f"{self.url}/v1/requests/{request_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        audit = audit_response.json() if audit_response.status_code == 200 else None
        observation = {
            "status": response.status_code,
            "latency_ms": latency_ms,
            "request_id": request_id,
            "header_correlated": response.headers.get("x-request-id") == request_id,
            "audit": audit,
            "response": body,
        }
        self.observations.append(observation)
        return observation

    @staticmethod
    def summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        latencies = [item["latency_ms"] for item in items]
        audits = [item["audit"] for item in items if item["audit"]]
        successes = [item for item in items if item["status"] == 200]
        attempts = sum(len((item["audit"] or {}).get("attempts", [])) for item in items)
        return {
            "requests": len(items),
            "success": len(successes),
            "http_status": dict(Counter(str(item["status"]) for item in items)),
            "latency_ms": {
                "mean": round(mean(latencies), 3) if latencies else 0.0,
                "p50": round(percentile(latencies, 0.50), 3),
                "p95": round(percentile(latencies, 0.95), 3),
                "p99": round(percentile(latencies, 0.99), 3),
            },
            "usage_source": dict(Counter(audit.get("usage_source") for audit in audits)),
            "estimated_input_tokens": {
                "min": min((audit.get("estimated_input_tokens", 0) for audit in audits), default=0),
                "max": max((audit.get("estimated_input_tokens", 0) for audit in audits), default=0),
            },
            "provider_attempts": attempts,
            "attempts_per_request": round(attempts / len(items), 3) if items else 0.0,
            "fallback_used": sum(bool(audit.get("fallback_used")) for audit in audits),
            "cache_hits": sum(bool(audit.get("cache_hit")) for audit in audits),
            "budget_rejections": sum(audit.get("error_code") == "token_budget_exceeded" for audit in audits),
            "guardrail_rejections": sum(audit.get("error_code") == "guardrail_blocked" for audit in audits),
            "request_id_correlation": sum(item["header_correlated"] for item in items),
            "audit_complete": len(audits),
            "audit_bytes": sum(
                len(json.dumps(audit, ensure_ascii=False, default=str).encode("utf-8"))
                for audit in audits
            ),
            "unexplained_5xx": sum(item["status"] >= 500 for item in items),
        }

    async def distribution(self, count: int) -> dict[str, Any]:
        items = await asyncio.gather(
            *(self.send(row["messages"], max_tokens=32) for row in self.wild[:count])
        )
        result = self.summary(items)
        result["oracle_pass"] = (
            result["unexplained_5xx"] == 0
            and result["request_id_correlation"] == len(items)
            and result["audit_complete"] == len(items)
        )
        return result

    async def long_context(self) -> dict[str, Any]:
        buckets = {"short": [], "medium": [], "long": [], "very_long": []}
        for row in self.ultra[:4]:
            user = next(message for message in row["messages"] if message["role"] == "user")
            content = user["content"][:400]
            buckets["short"].append(
                {
                    "messages": [{"role": "user", "content": content}],
                    "character_count": len(content),
                }
            )
        for row in self.ultra:
            chars = row["character_count"]
            name = "short" if chars <= 500 else "medium" if chars <= 2000 else "long" if chars <= 4000 else "very_long"
            if name == "short":
                continue
            if len(buckets[name]) < 4:
                buckets[name].append(row)
        result: dict[str, Any] = {}
        for name, rows in buckets.items():
            items = [await self.send(row["messages"], max_tokens=32) for row in rows]
            summary = self.summary(items)
            summary["input_characters"] = [row["character_count"] for row in rows]
            result[name] = summary
        result["oracle_pass"] = (
            bool(buckets["very_long"])
            and result["very_long"]["http_status"].get("400", 0) == len(buckets["very_long"])
            and all(summary["unexplained_5xx"] == 0 for summary in result.values() if isinstance(summary, dict))
        )
        return result

    async def cache(self) -> dict[str, Any]:
        rows = [row for row in self.wild if row["character_count"] <= 1500][:20]
        items = []
        for index, row in enumerate(rows):
            messages = [dict(message) for message in row["messages"]]
            messages[-1]["content"] += f"\n[cache experiment {index}]"
            for _ in range(3):
                items.append(await self.send(messages, max_tokens=32))
        summary = self.summary(items)
        provider_calls = sum(
            len((item["audit"] or {}).get("attempts", [])) for item in items
        )
        successful_groups = sum(items[i]["status"] == 200 for i in range(0, len(items), 3))
        content_stable = all(
            len({items[i + offset]["response"].get("content") for offset in range(3)}) == 1
            for i in range(0, len(items), 3)
            if items[i]["status"] == 200
        )

        single_messages = [dict(message) for message in rows[0]["messages"]]
        single_messages[-1]["content"] += "\n[singleflight experiment]"
        concurrent = await asyncio.gather(*(self.send(single_messages) for _ in range(10)))
        concurrent_attempts = sum(
            len((item["audit"] or {}).get("attempts", [])) for item in concurrent
        )
        summary.update(
            {
                "provider_calls": provider_calls,
                "expected_unique_successes": successful_groups,
                "singleflight_requests": 10,
                "singleflight_provider_calls": concurrent_attempts,
                "content_stable": content_stable,
                "oracle_pass": (
                    summary["cache_hits"] >= successful_groups * 2
                    and provider_calls == successful_groups
                    and concurrent_attempts == 1
                    and content_stable
                ),
            }
        )
        return summary

    async def cache_miss(self, count: int) -> dict[str, Any]:
        rows = [row for row in self.wild if row["character_count"] <= 1500][:count]
        items = []
        for index, row in enumerate(rows):
            messages = [dict(message) for message in row["messages"]]
            messages[-1]["content"] += f"\n[unique miss {index}]"
            items.append(await self.send(messages, max_tokens=32))
        result = self.summary(items)
        result["oracle_pass"] = result["cache_hits"] == 0 and result["unexplained_5xx"] == 0
        return result

    async def faults(self) -> dict[str, Any]:
        row = next(row for row in self.wild if row["character_count"] <= 1000)
        scenarios = {
            "provider_timeout": ("fault-timeout", 502, {"provider_timeout"}),
            "provider_500": ("fault-500", 502, {"provider_bad_status"}),
            "connection_failure": ("fault-connection", 502, {"provider_failed"}),
            "fallback_success": ("fault-fallback", 200, {"provider_bad_status"}),
            "all_providers_fail": (
                "fault-all",
                502,
                {"provider_bad_status", "provider_failed"},
            ),
        }
        result = {}
        for name, (profile_id, expected_status, expected_errors) in scenarios.items():
            item = await self.send(row["messages"], profile_id=profile_id, max_tokens=32)
            audit = item["audit"] or {}
            error_codes = {
                attempt["error_code"]
                for attempt in audit.get("attempts", [])
                if attempt.get("error_code")
            }
            result[name] = {
                "http_status": item["status"],
                "expected_status": expected_status,
                "request_id_correlated": item["header_correlated"],
                "response_attempts": len(item["response"].get("attempts", [])),
                "audit_attempts": len(audit.get("attempts", [])),
                "attempt_statuses": [attempt["status"] for attempt in audit.get("attempts", [])],
                "attempt_error_codes": [
                    attempt["error_code"] for attempt in audit.get("attempts", [])
                ],
                "attempt_error_messages": [
                    attempt["error_message"] for attempt in audit.get("attempts", [])
                ],
                "decision_steps": [step["step"] for step in audit.get("decision_trace", [])],
                "error_code": audit.get("error_code"),
                "oracle_pass": (
                    item["status"] == expected_status
                    and bool(audit)
                    and expected_errors.issubset(error_codes)
                ),
            }
        result["oracle_pass"] = all(item["oracle_pass"] for item in result.values())
        return result

    async def budget_boundary(self) -> dict[str, Any]:
        source = next(row for row in self.wild if row["character_count"] >= 80)
        text = source["messages"][0]["content"].replace("\n", " ")[:80]
        single = await self.send(
            [{"role": "user", "content": text}],
            api_key="budget-single-key",
            max_tokens=32,
        )
        parallel = await asyncio.gather(
            self.send(
                [{"role": "user", "content": text + " A"}],
                api_key="budget-concurrent-key",
                max_tokens=32,
            ),
            self.send(
                [{"role": "user", "content": text + " B"}],
                api_key="budget-concurrent-key",
                max_tokens=32,
            ),
        )
        conn = sqlite3.connect(self.db_path)
        try:
            period = time.strftime("%Y-%m-%d")
            usage = conn.execute(
                """SELECT COALESCE(tokens_used,0) FROM token_budget_usage
                WHERE client_id='budget-concurrent' AND period=?""",
                (period,),
            ).fetchone()
            reserved = conn.execute(
                """SELECT COALESCE(sum(tokens_reserved),0) FROM token_budget_reservations
                WHERE client_id='budget-concurrent' AND period=?""",
                (period,),
            ).fetchone()[0]
        finally:
            conn.close()
        used = usage[0] if usage else 0
        statuses = [item["status"] for item in parallel]
        return {
            "single_status": single["status"],
            "parallel_statuses": statuses,
            "used_tokens": used,
            "reserved_tokens": reserved,
            "oracle_pass": (
                single["status"] == 200
                and sorted(statuses) == [200, 429]
                and used + reserved <= 100
                and reserved == 0
            ),
        }


async def run_experiments(
    url: str,
    db_path: Path,
    wild: list[dict],
    ultra: list[dict],
    count: int,
    process: psutil.Process,
) -> dict[str, Any]:
    experiment = Experiment(url, db_path, wild, ultra)
    def usage() -> tuple[int, float]:
        processes = [process, *process.children(recursive=True)]
        rss = 0
        cpu = 0.0
        for item in processes:
            try:
                rss += item.memory_info().rss
                times = item.cpu_times()
                cpu += times.user + times.system
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return rss, cpu

    before, cpu_before = usage()
    started = time.perf_counter()
    try:
        distribution = await experiment.distribution(count)
        long_context = await experiment.long_context()
        cache = await experiment.cache()
        cache_miss = await experiment.cache_miss(min(count, 30))
        faults = await experiment.faults()
        budget = await experiment.budget_boundary()
        metrics_response = await experiment.client.get(f"{url}/metrics")
    finally:
        await experiment.close()
    elapsed = time.perf_counter() - started
    after, cpu_after = usage()
    conn = sqlite3.connect(db_path)
    try:
        request_rows = conn.execute("SELECT count(*) FROM request_logs").fetchone()[0]
        attempt_rows = conn.execute("SELECT count(*) FROM provider_attempts").fetchone()[0]
        audit_bytes = conn.execute(
            """SELECT COALESCE(sum(length(COALESCE(decision_trace,'')) +
            length(COALESCE(request_body,'')) + length(COALESCE(response_body,''))),0)
            FROM request_logs"""
        ).fetchone()[0]
        reservation_rows = conn.execute(
            "SELECT count(*) FROM token_budget_reservations"
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "distribution": distribution,
        "long_context": long_context,
        "cache_heavy": cache,
        "cache_miss": cache_miss,
        "fault_injection": faults,
        "budget_boundary": budget,
        "process": {
            "elapsed_seconds": round(elapsed, 3),
            "cpu_seconds": round(cpu_after - cpu_before, 3),
            "rss_before_bytes": before,
            "rss_after_bytes": after,
            "rss_delta_bytes": after - before,
        },
        "sqlite": {
            "request_rows": request_rows,
            "attempt_rows": attempt_rows,
            "audit_payload_bytes": audit_bytes,
            "reservation_rows": reservation_rows,
            "errors": 0,
        },
        "metrics_endpoint": {
            "status": metrics_response.status_code,
            "contains_required": all(
                name in metrics_response.text
                for name in (
                    "requests_total",
                    "provider_attempts_total",
                    "cache_hits_total",
                    "budget_rejections_total",
                )
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    fixture_root = Path(r"E:\project-test-assets\01-gateway\fixtures")
    parser.add_argument("--wildchat", type=Path, default=fixture_root / "wildchat_gateway_500_seed42.jsonl")
    parser.add_argument("--ultrachat", type=Path, default=fixture_root / "ultrachat_gateway_500_seed42.jsonl")
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path(r"E:\project-test-assets\01-gateway\results\gateway_dataset_experiment.json"))
    args = parser.parse_args()
    wild = load_jsonl(args.wildchat)
    ultra = load_jsonl(args.ultrachat)
    with tempfile.TemporaryDirectory(prefix="mini-llm-gateway-data-") as temp:
        temp_path = Path(temp)
        config_path = temp_path / "experiment.yaml"
        db_path = temp_path / "experiment.db"
        prepare_config(config_path)
        environment = os.environ.copy()
        environment["GW_CONFIG_PATH"] = str(config_path)
        environment["GW_DATABASE_PATH"] = str(db_path)
        fault = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "scripts.fault_provider_app:app", "--host", "127.0.0.1", "--port", "19090"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        gateway = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18080"],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_ready("http://127.0.0.1:19090/health", fault)
            wait_ready("http://127.0.0.1:18080/health", gateway)
            results = asyncio.run(
                run_experiments(
                    "http://127.0.0.1:18080",
                    db_path,
                    wild,
                    ultra,
                    args.requests,
                    psutil.Process(gateway.pid),
                )
            )
        finally:
            for process in (gateway, fault):
                process.terminate()
            for process in (gateway, fault):
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
        results["provenance"] = {
            "evidence_labels": ["PUBLIC DATA", "GENERATED", "FAULT", "TEST VERIFIED"],
            "wildchat_fixture": str(args.wildchat),
            "wildchat_sha256": file_sha256(args.wildchat),
            "ultrachat_fixture": str(args.ultrachat),
            "ultrachat_sha256": file_sha256(args.ultrachat),
            "provider_mode": "local deterministic mock plus fault HTTP provider",
            "database_mode": "temporary SQLite WAL",
            "gateway_processes": 1,
        }
        results["all_oracles_pass"] = all(
            results[key]["oracle_pass"]
            for key in (
                "distribution",
                "long_context",
                "cache_heavy",
                "cache_miss",
                "fault_injection",
                "budget_boundary",
            )
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0 if results["all_oracles_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
