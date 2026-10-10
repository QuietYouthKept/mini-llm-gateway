# PostgreSQL Outage Root Cause Analysis

Date: 2026-10-10 (Asia/Shanghai)
Test branch: `codex/wave5-release-hardening`
Baseline source commit: `3f57ce5d8cabbea148cc74c5023c2e5277ebd005`

## Findings

Two independent defects affected the original outage result.

1. The system resolver can block far beyond libpq's `connect_timeout`. In the earlier direct experiment, resolving Docker service name `postgres` while unavailable took about 8.006 seconds; `psycopg.connect(..., connect_timeout=1)` took about 8.319 seconds. Connecting to the already-resolved container IP with a 0.5-second socket timeout took about 0.501 seconds. The values were captured during the investigation; the original one-off terminal transcript was not retained as a standalone raw file, so treat these three numbers as supporting observations, not the release gate's primary evidence.
2. Database-unavailable handling returned before releasing the local singleflight owner. Concurrent requests with the same cache key waited until the 5-second request deadline. The new regression test first reproduced the error (HTTP 500 due to a network exception being misclassified), then passed after network errors were classified as database unavailability and the local owner/distributed lease was released on this branch.
3. The first repeat probe used an explicitly named, shared Docker network. Other Wave 5 Compose projects could therefore answer the same `postgres` DNS name. This caused mixed HTTP 503/200 outcomes. Those raw files are retained as `pg-outage-reused-client-repeat3.json` and `pg-outage-p1-fix-repeat3.json`, but are **invalid for acceptance** due to topology contamination.

## Valid isolated experiment

`pg-outage-p1-isolated-repeat3.json` uses a project-scoped Compose network (`mini-llm-gateway-wave5-p1-isolated_isolated`) and a SIGKILL PostgreSQL fault. The gateway runs in a Linux/amd64 Docker container; probes use a reusable `httpx.Client` over host TCP. Each of 20 and 50 concurrency was repeated three times.

| Concurrency | Repetitions | Chat status | Client P95 range | Client max | `/live` | `/ready` | Request audit rows | Reservation rows |
|---|---:|---|---:|---:|---|---|---:|---:|
| 20 | 3 | 20/20 returned 503 each round | 2.03–2.11 s | 2.11 s | 200; 15–32 ms | 503; 765–766 ms | 0 | 0 |
| 50 | 3 | 50/50 returned 503 each round | 2.48–2.55 s | 2.56 s | 200; 0–16 ms | 503; 765–781 ms | 0 | 0 |

The script waited for PostgreSQL restart and readiness recovery after each outage, then queried the database for every generated request ID. No audit or reservation was written for these failures; no persistence is claimed for requests rejected before reservation. The latest database worker max observed in the scrape was about 2.004 seconds. `/live` server-side response-start samples were below 9 ms in the cumulative histogram; event-loop lag samples were below 9 ms. Client timings and server histogram timings are distinct measurements.

The probe oracle passed (process exit 0) and preserved the full input requests, response status/duration, database state queries, metric excerpts, and log excerpts. This proves the tested outage/recovery path only; it does not prove Commit-Unknown, mid-transaction process death, SIGTERM during settlement, or all reservation reconciliation interleavings.

## Code change

`PostgreSQLConnection.connect()` resolves a single DNS hostname at startup and supplies `hostaddr` while retaining `host` for TLS hostname validation. A failed connection schedules one deduplicated background DNS refresh on a single-worker executor. Explicit `hostaddr`, literal IP, Unix socket, and multi-host DSNs are not rewritten. The application circuit fails closed, and the network-error path now releases local singleflight waiters without asserting that an unpersisted request was audited.

The DNS cache is process-local and currently has no explicit entry-count cap. Multi-host DSNs retain the system resolver behavior. These are follow-up risks, not proven safe cases.

## Evidence

- Valid raw matrix: `evidence/wave5/pg-outage-p1-isolated-repeat3.json`
- Compact raw summary: `evidence/wave5/pg-outage-p1-isolated-summary.csv` and `.json`
- Prior contaminated raw matrices: `pg-outage-reused-client-repeat3.json`, `pg-outage-p1-fix-repeat3.json` (retained, not used as passes)
- Regression test: `tests/integration/test_chat_api.py::test_database_unavailable_releases_local_singleflight`
- Database integration: `evidence/wave5/final-gates/postgres-integration.log`
- Database repository integration coverage: `evidence/wave5/final-gates/postgres-coverage.txt` (59% for the dedicated probe run; not merged into pytest-only coverage)
