# PostgreSQL / Redis Fixed-Resource Capacity Experiment

**Experiment:** `overnight-20261010`, source `9fd1cdca5318a8b00e52b1a29176b7bd5fc66b77` plus the dirty-worktree identity recorded in the evidence checkpoint. **Status: PARTIAL; stopped by the correctness oracle at cell 12/36.** This is synthetic deterministic Mock Provider traffic against an isolated Gateway + PostgreSQL 16 + Redis 7 deployment, not model inference throughput or an SLO.

## Environment and controls

- Gateway: 2 vCPU / 1 GiB, read-only root filesystem, UID/GID 10001.
- PostgreSQL: 2 vCPU / 1 GiB; Redis: 1 vCPU / 512 MiB. Dedicated containers and databases; no unrelated containers were changed.
- Load generator: separate container; 10 s warm-up plus 30 s measurement per measured cell. Each cell had a distinct run ID. The planned matrix was concurrency 1/8/32/64 × target cache ratio 0/0.5/0.9 × 3 repetitions = 36 cells.
- The matrix stopped immediately after a database-invariant failure. No concurrency 32/64 cells or later cells were attempted.

## Results actually collected

| Concurrency | Target cache | Repetition | Requests | Success | RPS | P50 ms | P95 ms | P99 ms | DB oracle |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 0.0 | 1 | 144 | 100% | 4.737 | 189.325 | 324.237 | 471.558 | pass |
| 1 | 0.0 | 2 | 144 | 100% | 4.780 | 191.510 | 318.150 | 401.810 | pass |
| 1 | 0.0 | 3 | 164 | 100% | 5.320 | 175.540 | 283.290 | 362.840 | pass |
| 1 | 0.5 | 1 | 184 | 100% | 6.110 | 168.660 | 269.270 | 370.870 | pass |
| 1 | 0.5 | 2 | 176 | 100% | 5.830 | 177.100 | 288.930 | 349.710 | pass |
| 1 | 0.5 | 3 | 184 | 100% | 6.040 | 172.560 | 296.570 | 359.310 | pass |
| 1 | 0.9 | 1 | 244 | 100% | 8.090 | 153.940 | 270.410 | 366.560 | pass |
| 1 | 0.9 | 2 | 292 | 100% | 9.720 | 47.280 | 222.900 | 287.200 | pass |
| 1 | 0.9 | 3 | 248 | 100% | 8.140 | 148.460 | 278.380 | 339.250 | pass |
| 8 | 0.0 | 1 | 544 | 100% | 17.170 | 373.530 | 795.830 | 1,098.800 | pass |
| 8 | 0.0 | 2 | 704 | 100% | 23.100 | 288.230 | 507.960 | 613.520 | pass |
| 8 | 0.0 | 3 | 1,984 | 0% | 65.121 attempted | 101.877 | 204.449 | 290.056 | **stop** |

The last cell returned 1,984 HTTP 503 responses classified `database_unavailable`; the measured latency is failed-request latency, not successful service capacity. `65.121` is attempted request rate only and must not be described as throughput. The final cell's pre-reconciliation database snapshot had 3,565 reservations, 3,563 settled, and 2 expired `reserved` rows; receipt duplicates were zero. Load was stopped before reconciliation.

## Recovery and persistence oracle

The explicit lease reconciliation returned 2 and recorded two `orphaned_released / reservation_lease_expired` audit outcomes. The post-reconciliation snapshot was:

- Reservations: 3,565 total; 3,563 settled, 2 released, 0 reserved, 0 uncertain.
- `stream_finalizations`: 3,565 terminal receipts, 0 duplicate request IDs.
- Request audit rows: 4,132; provider attempts: 3,563. The 2 released orphan reservations have no provider attempt; their release is separately audited.
- No usage was charged for the two orphan releases; the recorded settled usage remained 297,670 tokens.

The final real PostgreSQL integration probe also passed: concurrent finalization replay, audit-transaction rollback, negative usage rejection, orphan reconciliation, cold budget reservation, budget rejection, and a TCP COMMIT-ACK-loss scenario all returned their expected oracles. In the ACK-loss case, COMMIT completed on the wire, the client observed `psycopg.OperationalError`, the receipt was recovered, replay was idempotent, and the database ended with one receipt, one audit, one attempt, and 12 billed tokens.

## Interpretation and remaining diagnosis

- Concurrency 1 was 100% successful for all 9 completed cells. At concurrency 8, the first two cells were 100%; the third abruptly failed completely. These observations are not a stable capacity curve because the matrix was intentionally censored at the first correctness failure.
- Concurrency 32 and 64: **not executed**. P95/P99 at those levels: **unknown**.
- No optimization and no fair before/after experiment were completed. Do not claim a performance improvement.
- A plausible cause is same-client PostgreSQL advisory-lock serialization interacting with short lock/statement deadlines; the 3.59 s observed maximum reservation execution was near the 3 s statement timeout. This is only a hypothesis: SQLSTATE, `pg_stat_activity` wait events, and lock-wait data were not captured at the failure instant. The broad `database_unavailable` classification may also have converted query timeout into a dependency failure. Both require a targeted follow-up experiment.
- Redis probes passed separately: global rate limiting, exact shared cache, distributed singleflight, stale-owner fencing, lease expiry, and explicit fail-open/fail-closed behavior. In the two-real-Uvicorn probe, 20 rate-limited requests produced 10 admissions and 10 rejections; singleflight executed the provider once across replicas; a PostgreSQL shared-budget race returned one 200 and one 429 with one settled reservation and two audit rows.

## Raw evidence

All raw machine-readable results are outside Git at `E:\project-test-assets\01-gateway\results\overnight-sprint-20261010T155645Z\`. Key files: `capacity-matrix\matrix-summary.json`, per-cell `summary.json` and `database-snapshot.json`, `database-invariants\before-reconciliation.json`, `after-reconciliation.json`, `reconciled-state.txt`, `postgres-final-probe.log`, `provider-faults\redis-adapter-probe.log`, and `redis-two-replica-probe.log`. The evidence manifest records file hashes; no raw data samples are included in the report.
