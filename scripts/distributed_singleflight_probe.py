"""Validate Redis-backed cross-replica singleflight against two live gateways.

Start an isolated Redis and two Uvicorn processes with ``GW_REDIS_URL`` and
``GW_CACHE_BACKEND=redis`` first.  The probe intentionally uses only the
checked-in mock provider and a synthetic prompt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import httpx

from app.infrastructure.redis.singleflight import RedisSingleFlight


async def probe(gateway_a: str, gateway_b: str, redis_url: str) -> dict[str, object]:
    import redis

    client = redis.Redis.from_url(redis_url, decode_responses=True, protocol=2)
    for pattern in ("llmgw:cache:*", "llmgw:sf:*"):
        keys = list(client.scan_iter(match=pattern))
        if keys:
            client.delete(*keys)

    payload = {
        "profile": "fast-chat",
        "messages": [{"role": "user", "content": "distributed singleflight probe"}],
        "max_tokens": 16,
    }
    headers = {"Authorization": "Bearer demo-key"}
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=5.0, trust_env=False) as http:
        responses = await asyncio.gather(
            http.post(f"{gateway_a}/v1/chat", headers=headers, json=payload),
            http.post(f"{gateway_b}/v1/chat", headers=headers, json=payload),
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    bodies = [response.json() for response in responses]

    # A separate short lease models a leader process disappearing before it can
    # publish cache content. The follower must acquire after TTL, never by
    # deleting an unknown owner's key.
    leader = RedisSingleFlight(redis_url, ttl_ms=120, prefix="llmgw:sf-probe")
    follower = RedisSingleFlight(redis_url, ttl_ms=120, prefix="llmgw:sf-probe")
    stale_key = "leader-crash"
    stale_leader_acquired = leader.try_acquire(stale_key)
    stale_follower_initial = follower.try_acquire(stale_key)
    await asyncio.sleep(0.15)
    stale_follower_recovered = follower.try_acquire(stale_key)
    follower.release(stale_key)
    leader.close()
    follower.close()
    client.close()

    provider_executions = sum(
        1 for body in bodies for attempt in body.get("attempts", []) if attempt["status"] == "success"
    )
    result = {
        "status_codes": [response.status_code for response in responses],
        "cache_hits": [body.get("cache_hit") for body in bodies],
        "responses_equivalent": bodies[0].get("content") == bodies[1].get("content"),
        "provider_executions": provider_executions,
        "latency_ms": elapsed_ms,
        "stale_leader_acquired": stale_leader_acquired,
        "stale_follower_initial": stale_follower_initial,
        "stale_follower_recovered": stale_follower_recovered,
    }
    result["oracle_pass"] = (
        result["status_codes"] == [200, 200]
        and provider_executions == 1
        and result["responses_equivalent"] is True
        and stale_leader_acquired is True
        and stale_follower_initial is False
        and stale_follower_recovered is True
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway-a", default="http://127.0.0.1:18084")
    parser.add_argument("--gateway-b", default="http://127.0.0.1:18085")
    parser.add_argument("--redis-url", default="redis://127.0.0.1:16379/0")
    args = parser.parse_args()
    result = asyncio.run(
        probe(args.gateway_a.rstrip("/"), args.gateway_b.rstrip("/"), args.redis_url)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["oracle_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
