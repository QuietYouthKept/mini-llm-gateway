# Gateway hardening test cards

## GW-BUDGET-RACE-001

- Claim / invariant: two 15-token admissions at used=80 and limit=100 cannot both pass.
- Basis: hard-quota admission requires one database serialization point.
- Workload: two threads, two SQLite connections, synchronized start.
- Oracle: exactly one admitted; used plus reserved equals 95.
- Evidence: `test_budget_reservation_admission_is_atomic_across_connections`.
- Current result: `[TEST VERIFIED]`.
- Scope: this card proves the SQLite contract; PostgreSQL runtime evidence is in
  `GW-PG-001` in `public-dataset-production-evidence.md`.

## GW-CACHE-GOV-001

- Claim / invariant: exact cache hits cannot restore pre-guardrail provider output.
- Workload: response longer than output `max_chars`, then identical request.
- Oracle: first and second content are identical and truncated; second has no attempt.
- Evidence: `test_cache_stores_governed_output_not_raw_response`.
- Current result: `[TEST VERIFIED]`.

## GW-REPLAY-OFFLINE-001

- Claim / invariant: default offline replay has no provider side effect.
- Workload: counting provider plus recorded attempt signature.
- Oracle: call count remains zero.
- Evidence: `test_offline_replay_never_calls_provider`.
- Current result: `[TEST VERIFIED]`.

## GW-LOAD-001

- Claim / invariant: bounded local load produces correlated responses without DB errors.
- Workload: generated cache-heavy, cache-miss, long-prompt, timeout, and retry scenarios.
- Oracle: report RPS/percentiles/error rate/attempt ratio/cache ratio; no unclassified error.
- Seed / reproducibility: deterministic request index and prompt set in `scripts/load_test.py`.
- Current result: `[TEST VERIFIED]` on 2026-08-21 against Uvicorn on a real socket.
- Evidence: cache-heavy 20 requests at concurrency 5 had 0% errors, 118.15 RPS,
  p95 82.41 ms, and 0.80 cache-hit ratio; cache-miss had 0% errors and p95
  136.12 ms. See `docs/load-test-results-2026-08-21.md`.
- Scope: newer bounded process results and separate Redis/PostgreSQL evidence are
  recorded in the 2026-08-23 reports; production capacity is not claimed.

## GW-MULTI-001

- Claim / invariant: SQLite budget admission and audit are shared across two
  processes, while in-memory rate limit and cache remain explicitly local.
- Workload: two Uvicorn processes share one SQLite DB; simultaneous 60k-token
  reservations against a 100k budget; repeated cache/rate probes on A and B.
- Oracle: budget statuses are exactly 200/429; both audits can be read through
  A; first cache request on each replica is a miss; each replica independently
  admits three burst requests.
- Evidence: `scripts/multi_replica_probe.py` returned `passed=true`.
- Current result: `[TEST VERIFIED]` on 2026-08-21.
- Scope: this remains the local-adapter ownership card. Redis and PostgreSQL
  behavior is verified separately in `GW-REDIS-001` and `GW-PG-001`.
