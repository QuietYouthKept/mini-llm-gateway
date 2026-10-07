# Ten-minute demo guide

Use mock providers only. Start with the README quickstart, then run these in
order; each demonstration is deterministic and tied to an oracle.

1. **Happy path:** `scripts/final_demos.py` demo 1 shows provider, request ID,
   decision trace, and audit attempt.
2. **Fallback:** demo 2 shows an erroring primary, retry, stable fallback, and
   recorded attempt chain.
3. **Cache:** demo 3 shows first miss, second governed cache hit, and zero
   provider attempts on the hit.
4. **Budget race:** demo 4 shows one admission at a shared quota boundary.
5. **Redis two replicas:** start two gateways with shared Redis and run
   `scripts/redis_replica_probe.py`; global limiter results are the oracle.
6. **Distributed singleflight:** run `scripts/distributed_singleflight_probe.py`;
   oracle is `provider_executions == 1` plus TTL crash recovery.

Avoid presenting health checks or CRUD as the main value. Show the decision
trace, failure path, ownership boundary, and evidence instead.
