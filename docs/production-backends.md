# Production backend status

The application layer depends only on repository/cache/limiter/tracing ports.
The composition root selects concrete adapters; `ChatService` contains no
SQLite/PostgreSQL or local/Redis branching.

## Implemented adapters

| Capability | Local default | Shared adapter | 2026-08-23 runtime evidence |
| --- | --- | --- | --- |
| budget + request audit | SQLite | PostgreSQL (`psycopg`) | migrations repeated safely; two-connection budget race; audit rollback; two Uvicorn replicas and cross-replica audit read |
| rate limit | memory | Redis Lua | two independent instances and two Uvicorn replicas enforced one global limit |
| exact cache + singleflight | memory | Redis | A/B simultaneous cold miss executed the provider once; owner-safe TTL lease recovered after simulated leader loss |
| tracing | bounded memory | OpenTelemetry OTLP/HTTP | success and fallback/error traces received by a real collector |

Select PostgreSQL with `GW_DATABASE_URL`. Set `GW_REDIS_URL` for the Redis rate
limiter and additionally set `GW_CACHE_BACKEND=redis` for the shared cache. Set
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to enable OTLP/HTTP export. Install the
optional dependencies with `.[production]`.

PostgreSQL migrations take a transaction advisory lock, making simultaneous
replica startup safe. Budget admission and settlement use database locking and
enforce the reservation envelope: actual usage may settle below a reservation,
but a provider result above the reserved token/cost maximum fails explicitly and
the reservation is released. Request and attempt rows are written atomically.

Redis rate limiting uses an atomic Lua `INCR`/`PEXPIRE` operation. Redis cache
TTL is exact and cache values contain governed responses only. Redis cache
singleflight uses `SET NX PX` with a cryptographically random owner token and
Lua compare-and-delete unlock. Followers use bounded exponential polling and
re-read the cache. A stale owner is recovered by TTL; an unavailable Redis
degrades cache/singleflight to local behavior while the rate limiter defaults
to fail-closed (set `GW_REDIS_RATE_LIMIT_FAILURE_MODE=open` only with an
explicit risk decision).

## Operational boundary

Runtime verification is evidence that the adapters and contracts work; it is
not a claim of a fully operated production platform. Deployment owners still
need TLS and secret management, connection-pool sizing, backups/restores,
failover drills, Redis/PostgreSQL persistence policy, dashboards, alerts, and
capacity tests on target infrastructure. Circuit breakers and Prometheus
registries remain process-local and must be aggregated operationally.

Exact commands, oracles, environment details, and limitations are recorded in
[the formal test cards](test-cards/public-dataset-production-evidence.md).
