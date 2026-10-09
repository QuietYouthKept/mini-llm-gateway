"""Verify global Redis rate limiting and cross-replica exact cache behavior."""

from __future__ import annotations

import argparse
import asyncio
import json

import httpx


async def run(
    url_a: str,
    url_b: str,
    *,
    rate_api_key: str = "redis-rate-key",
    cache_api_key: str = "redis-cache-key",
    cache_nonce: str = "",
) -> dict:
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
        rate_payloads = [
            {
                "profile": "fast-chat",
                "messages": [{"role": "user", "content": f"redis global rate {index}"}],
                "max_tokens": 16,
            }
            for index in range(20)
        ]
        statuses = []
        for index, payload in enumerate(rate_payloads):
            base = url_a if index % 2 == 0 else url_b
            response = await client.post(
                f"{base}/v1/chat",
                headers={"Authorization": f"Bearer {rate_api_key}"},
                json=payload,
            )
            statuses.append(response.status_code)

        cache_payload = {
            "profile": "fast-chat",
            "messages": [{
                "role": "user",
                "content": f"redis cross replica exact cache {cache_nonce}",
            }],
            "max_tokens": 16,
        }
        first, second = await asyncio.gather(
            client.post(
                f"{url_a}/v1/chat",
                headers={"Authorization": f"Bearer {cache_api_key}"},
                json=cache_payload,
            ),
            client.post(
                f"{url_b}/v1/chat",
                headers={"Authorization": f"Bearer {cache_api_key}"},
                json=cache_payload,
            ),
        )
    first_body = first.json()
    second_body = second.json()
    return {
        "rate_requests": len(statuses),
        "rate_admitted": statuses.count(200),
        "rate_rejected": statuses.count(429),
        "rate_statuses": statuses,
        "cache_first_status": first.status_code,
        "cache_first_hit": first_body.get("cache_hit"),
        "cache_first_attempts": len(first_body.get("attempts", [])),
        "cache_second_status": second.status_code,
        "cache_second_hit": second_body.get("cache_hit"),
        "cache_second_attempts": len(second_body.get("attempts", [])),
        "cache_content_equal": first_body.get("content") == second_body.get("content"),
        "provider_executions": sum(
            1
            for body in (first_body, second_body)
            for attempt in body.get("attempts", [])
            if attempt["status"] == "success"
        ),
        "oracle_pass": (
            statuses.count(200) == 10
            and statuses.count(429) == 10
            and first.status_code == 200
            and sum(
                1
                for body in (first_body, second_body)
                for attempt in body.get("attempts", [])
                if attempt["status"] == "success"
            ) == 1
            and second.status_code == 200
            and first_body.get("content") == second_body.get("content")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-a", default="http://127.0.0.1:18084")
    parser.add_argument("--gateway-b", default="http://127.0.0.1:18085")
    args = parser.parse_args()
    result = asyncio.run(run(args.gateway_a.rstrip("/"), args.gateway_b.rstrip("/")))
    print(json.dumps(result, indent=2))
    return 0 if result["oracle_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
