"""Probe documented state scope across two running gateway processes."""

from __future__ import annotations

import argparse
import asyncio
import json

import httpx


async def main_async(a: str, b: str) -> tuple[dict, bool]:
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
        demo_headers = {"Authorization": "Bearer demo-key"}
        budget_payload = {
            "profile": "fast-chat",
            "messages": [{"role": "user", "content": "cross replica budget race"}],
            "max_tokens": 60000,
        }

        async def budget_call(url: str, request_id: str):
            headers = {**demo_headers, "x-request-id": request_id}
            return await client.post(url + "/v1/chat", json=budget_payload, headers=headers)

        budget_responses = await asyncio.gather(
            budget_call(a, "multi-budget-a"), budget_call(b, "multi-budget-b")
        )
        budget_statuses = [response.status_code for response in budget_responses]

        cache_payload = {
            "profile": "fast-chat",
            "messages": [{"role": "user", "content": "cross replica cache scope"}],
            "max_tokens": 64,
        }
        cache_a = await client.post(a + "/v1/chat", json=cache_payload, headers=demo_headers)
        cache_b = await client.post(b + "/v1/chat", json=cache_payload, headers=demo_headers)

        burst_headers = {"Authorization": "Bearer burst-key"}
        burst_payload = {
            "profile": "fast-chat",
            "messages": [{"role": "user", "content": "cross replica rate scope"}],
            "max_tokens": 64,
        }
        burst_a = [
            (await client.post(a + "/v1/chat", json=burst_payload, headers=burst_headers)).status_code
            for _ in range(4)
        ]
        burst_b = [
            (await client.post(b + "/v1/chat", json=burst_payload, headers=burst_headers)).status_code
            for _ in range(4)
        ]

        audit_statuses = [
            (
                await client.get(
                    a + f"/v1/requests/{request_id}",
                    headers=demo_headers,
                )
            ).status_code
            for request_id in ("multi-budget-a", "multi-budget-b")
        ]

    result = {
        "budget_statuses": budget_statuses,
        "cache_hit_on_a_then_b": [cache_a.json()["cache_hit"], cache_b.json()["cache_hit"]],
        "rate_statuses_a": burst_a,
        "rate_statuses_b": burst_b,
        "shared_audit_lookup_statuses": audit_statuses,
    }
    passed = (
        sorted(budget_statuses) == [200, 429]
        and result["cache_hit_on_a_then_b"] == [False, False]
        and burst_a == [200, 200, 200, 429]
        and burst_b == [200, 200, 200, 429]
        and audit_statuses == [200, 200]
    )
    return result, passed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", default="http://127.0.0.1:8881")
    parser.add_argument("--b", default="http://127.0.0.1:8882")
    args = parser.parse_args()
    result, passed = asyncio.run(main_async(args.a.rstrip("/"), args.b.rstrip("/")))
    print(json.dumps({"passed": passed, **result}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
