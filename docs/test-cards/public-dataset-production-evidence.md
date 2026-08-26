# Public-dataset and production-backend test cards

Evidence date: 2026-08-23. Labels are literal evidence classes:
`[PUBLIC DATA]`, `[FIXTURE]`, `[GENERATED]`, `[FAULT]`, `[TEST VERIFIED]`, and
`[UNVERIFIED]`. No prompt or response body is included in this document.

## GW-DATA-001 — deterministic public-data workload

- Claim / invariant: a bounded workload can be regenerated from the supplied
  WildChat and UltraChat Parquet files without mutating raw data.
- Dataset / labels: WildChat 529,428 raw / 523,975 eligible rows and UltraChat
  23,110 raw / eligible rows. `[PUBLIC DATA] [GENERATED] [FIXTURE]`.
- Seed / initial state: seed 42; sorted shard order; empty output targets.
- Workload: batch-stream Parquet, normalize roles/content, reject WildChat rows
  or turns marked toxic/redacted, reservoir-sample 500 rows per source.
- Observable evidence: metadata sidecars record source files, schema, counts,
  seed, hashes, timestamp, and `raw_data_mutated=false`.
- Oracle: exactly 500 valid records per file and recomputed SHA-256 equals
  metadata. WildChat `4deda7c80fe7782d96ec715a24dcb85a09ff6602decf628ede889f6a2eeb52aa`;
  UltraChat `a65c424aa218dee302e7a39632a65c3f74ceb43f33d61de7fadceb03c69f3620`.
- Result: `[TEST VERIFIED]`.
- Known limitation: filtering uses source annotations and syntactic validity; it
  is not a new semantic safety classification.

## GW-LONGCTX-001 — real multi-turn and long-context boundaries

- Claim / invariant: accepted context sizes complete with correlated audit;
  requests beyond configured aggregate input length fail before provider use.
- Dataset / labels: four UltraChat-derived records in each of short, medium,
  long, and very-long buckets. `[PUBLIC DATA] [FIXTURE] [TEST VERIFIED]`.
- Initial state / workload: fresh temporary SQLite WAL database and one Uvicorn
  process; four requests per bucket; deterministic local HTTP provider.
- Observable evidence: input character/token estimate, HTTP status, latency,
  attempts, request ID, audit completeness, and audit byte count.
- Oracle / result: short/medium/long were 4/4 HTTP 200; very-long was 4/4 HTTP
  400 with zero provider attempts; all audit and request-ID checks passed.
- Known limitation: token counts are gateway estimates unless provider usage is
  returned; the local provider is not a model-quality evaluation.

## GW-CACHE-001 — cache hit, miss, and local singleflight

- Claim / invariant: repeated exact requests are stable and skip providers;
  unique requests miss; simultaneous local misses coalesce.
- Dataset / labels: WildChat-derived prompts. `[PUBLIC DATA] [GENERATED]
  [TEST VERIFIED]`.
- Initial state / workload: empty cache; 20 unique prompts repeated three times,
  30 unique prompts, then ten simultaneous identical requests.
- Observable evidence: response `cache_hit`, attempt lists, content equality,
  provider call count, and metrics.
- Oracle / result: 20 provider calls plus 40 hits (0.667 hit ratio); unique set
  had 30 attempts and no hits; ten concurrent identical requests made one call.
- Known limitation: singleflight is process-local. Redis shares values across
  replicas but does not provide distributed singleflight.

## GW-FAULT-001 — HTTP provider failures and fallback

- Claim / invariant: timeout, HTTP 500, connection/DNS failure, partial fallback,
  and total failure produce deterministic status, attempt, audit, and trace data.
- Dataset / labels: WildChat-derived prompt plus deterministic local fault server.
  `[PUBLIC DATA] [FAULT] [TEST VERIFIED]`.
- Workload / fault: timeout and 500 each retried twice; invalid DNS host;
  primary-500 to mock fallback; then 500 plus DNS total failure.
- Observable evidence: response status/error, response attempts when successful,
  persisted attempt chain, decision trace, request ID, and metrics.
- Oracle / result: isolated failures ended as HTTP 502 with expected domain error;
  partial fallback returned 200 after three attempts; total failure returned 502
  after four attempts. All experiment oracles passed.
- Known limitation: provider is a local protocol-compatible fault injector, not
  a paid external API. `[UNVERIFIED]` for third-party vendor behavior.

## GW-BUDGET-001 — strict reservation and concurrency boundary

- Claim / invariant: used plus reserved usage never exceeds the configured
  budget; settle cannot exceed its reservation; cancellation releases state.
- Dataset / labels: distinct real-data-derived prompts. `[PUBLIC DATA]
  [TEST VERIFIED]`.
- Initial state / workload: 100-token limit; one successful request followed by
  two concurrent unique requests near the boundary.
- Observable evidence: statuses, budget snapshot, reservation table, audit, and
  targeted reserve/settle/release unit tests.
- Oracle / result: concurrent statuses were exactly 200 and 429; used=52,
  reserved=0, total <=100. Over-settlement errors explicitly; under-settlement
  releases unused capacity; duplicate settle is rejected; release is idempotent.
- Known limitation: cost correctness depends on configured prices and provider
  usage quality.

## GW-REDIS-001 — global rate limit and cross-replica cache

- Claim / invariant: two gateway replicas using one Redis enforce one global
  rate window and share exact cache values.
- Labels: Redis 7 container, two real Uvicorn processes. `[TEST VERIFIED]`.
- Initial state / workload: empty Redis; alternate 20 requests between replicas
  under limit 10; send one identical cache request through A then B.
- Observable evidence: HTTP status sequence, response cache flags, attempts, and
  content hash/equality.
- Oracle / result: exactly 10 admitted and 10 rejected; A was a one-attempt miss;
  B was a zero-attempt hit with identical content. `oracle_pass=true`.
- Known limitation: no Redis cluster/failover, TLS, eviction, or outage test.
  Those deployment properties remain `[UNVERIFIED]`.

## GW-PG-001 — PostgreSQL repository and replica behavior

- Claim / invariant: migrations are safe under repeat/simultaneous startup;
  budget admission serializes globally; audit writes are atomic and readable
  across replicas.
- Labels: disposable PostgreSQL 16 and two Uvicorn processes. `[FAULT]
  [TEST VERIFIED]`.
- Initial state / workload: fresh database; run migrations twice; commit 80 of
  100 then race two 15-token reservations on separate connections; inject a
  trigger failure on attempt two; start two replicas and read A's audit via B.
- Observable evidence: migration exit, budget snapshot, row counts after injected
  failure, HTTP response, and cross-replica audit response.
- Oracle / result: one admission and one rejection, 80 used plus 15 reserved;
  failed transaction left zero request/attempt rows; two replicas started
  concurrently and cross-replica audit returned HTTP 200 with one attempt.
- Known limitation: HA/failover, backup/restore, TLS, pool saturation, and long
  production-duration behavior remain `[UNVERIFIED]`.

## GW-OTEL-001 — OTLP trace export without prompt bodies

- Claim / invariant: success and error/fallback paths export correlated spans
  without prompt, response, or API-key attributes.
- Labels: OpenTelemetry Collector Contrib 0.135.0. `[FAULT] [TEST VERIFIED]`.
- Workload: one successful request and one fallback/error request through real
  Uvicorn with OTLP/HTTP configured.
- Observable evidence: collector debug exporter output for `gateway.request`,
  `routing.resolve`, and `provider.attempt` spans and bounded attributes.
- Oracle / result: success exported three spans; error/fallback exported five;
  provider/status metadata was present and sensitive bodies/keys were absent.
- Known limitation: collector persistence, sampling policy, backend retention,
  dashboards, and alerts remain `[UNVERIFIED]`.

## GW-CLEAN-001 — clean reproduction

- Claim / invariant: success does not depend on the original working tree's
  installed package state or caches.
- Labels: fresh copied checkout and fresh Python 3.11 virtual environment.
  `[TEST VERIFIED]`.
- Initial state / workload: copy source while excluding `.git`, `.venv`, caches,
  generated databases and egg-info; install `.[dev]`; run pytest, Ruff, eval,
  security eval, and demo.
- Oracle / result: all commands exit zero; the final clean run reported 116
  tests, eval 7/7, security 8/8, and every original/final demo scenario passed.
- Known limitation: this proves source/install reproducibility on the recorded
  Windows/Python environment, not every supported OS/runtime.

## Replay semantics

Offline replay is a deterministic **routing-decision simulation** over persisted
metadata and the current config. It proves no-provider side effects and detects
decision drift; it does not reproduce remote provider execution. Live replay is
explicit opt-in and is subject to the provider limitations above.
