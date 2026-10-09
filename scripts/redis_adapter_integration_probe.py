"""Exercise Redis adapters against a live Redis server with isolated keys."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.domain.errors import RateLimitBackendUnavailableError
from app.domain.ports.provider_port import ChatResponse
from app.infrastructure.redis.prompt_cache import RedisPromptCache
from app.infrastructure.redis.rate_limiter import RedisRateLimiter
from app.infrastructure.redis.singleflight import RedisSingleFlight


def run(url: str) -> dict[str, object]:
    prefix = f"wave3:{uuid.uuid4().hex}"
    rate_a = RedisRateLimiter(url, prefix=f"{prefix}:rate")
    rate_b = RedisRateLimiter(url, prefix=f"{prefix}:rate")
    cache_a = RedisPromptCache(url, ttl_ms=5000, prefix=f"{prefix}:cache")
    cache_b = RedisPromptCache(url, ttl_ms=5000, prefix=f"{prefix}:cache")
    flight_a = RedisSingleFlight(url, ttl_ms=100, prefix=f"{prefix}:flight")
    flight_b = RedisSingleFlight(url, ttl_ms=100, prefix=f"{prefix}:flight")
    try:
        barrier = Barrier(20)

        def check_rate(index: int) -> bool:
            barrier.wait()
            limiter = rate_a if index % 2 else rate_b
            return limiter.check("shared-client", 10).allowed

        with ThreadPoolExecutor(max_workers=20) as pool:
            rate_decisions = list(pool.map(check_rate, range(20)))

        expected = ChatResponse(
            content="synthetic shared response",
            provider_id="synthetic-provider",
            model="synthetic-model",
            usage={"billed_input": 3, "billed_output": 2},
        )
        cache_a.put("one-key", expected)
        cached = cache_b.get("one-key")
        cache_shared = bool(
            cached
            and cached.content == expected.content
            and cached.provider_id == expected.provider_id
            and cached.usage == expected.usage
        )

        owner_acquired = flight_a.try_acquire("lease")
        follower_blocked = flight_b.try_acquire("lease") is False
        time.sleep(0.15)
        follower_recovered = flight_b.try_acquire("lease")
        stale_owner_cannot_release = flight_a.release("lease") is False
        new_owner_releases = flight_b.release("lease") is True

        # Exercise the configured fail-closed contract when a live Redis client
        # loses its network route after successful construction.
        closed = RedisRateLimiter(url, prefix=f"{prefix}:closed", failure_mode="closed")
        open_limiter = RedisRateLimiter(url, prefix=f"{prefix}:open", failure_mode="open")
        original_closed = closed._client.execute_command
        original_open = open_limiter._client.execute_command

        def unavailable(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise ConnectionError("injected Redis outage")

        closed._client.execute_command = unavailable
        open_limiter._client.execute_command = unavailable
        closed_failure_classified = False
        try:
            closed.check("outage", 10)
        except RateLimitBackendUnavailableError:
            closed_failure_classified = True
        open_allowed = open_limiter.check("outage", 10).allowed
        closed._client.execute_command = original_closed
        open_limiter._client.execute_command = original_open
        closed.close()
        open_limiter.close()

        result: dict[str, object] = {
            "rate_limit_total": len(rate_decisions),
            "rate_limit_admitted": sum(rate_decisions),
            "rate_limit_rejected": len(rate_decisions) - sum(rate_decisions),
            "shared_cache_exact": cache_shared,
            "singleflight_owner_acquired": owner_acquired,
            "singleflight_follower_blocked": follower_blocked,
            "singleflight_follower_recovers_after_lease_expiry": follower_recovered,
            "singleflight_stale_owner_cannot_release_new_lease": stale_owner_cannot_release,
            "singleflight_new_owner_releases": new_owner_releases,
            "redis_outage_fail_closed_classified": closed_failure_classified,
            "redis_outage_fail_open_allows": open_allowed,
        }
        result["oracle_pass"] = all(
            (
                result["rate_limit_total"] == 20,
                result["rate_limit_admitted"] == 10,
                result["rate_limit_rejected"] == 10,
                result["shared_cache_exact"],
                result["singleflight_owner_acquired"],
                result["singleflight_follower_blocked"],
                result["singleflight_follower_recovers_after_lease_expiry"],
                result["singleflight_stale_owner_cannot_release_new_lease"],
                result["singleflight_new_owner_releases"],
                result["redis_outage_fail_closed_classified"],
                result["redis_outage_fail_open_allows"],
            )
        )
        return result
    finally:
        rate_a.close()
        rate_b.close()
        cache_a.close()
        cache_b.close()
        flight_a.close()
        flight_b.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--redis-url", default="redis://127.0.0.1:6379/0")
    args = parser.parse_args()
    result = run(args.redis_url)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["oracle_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
