# Wave 4 Reliability Report

## Changes made

`BoundedBlockingIO` uses a bounded ThreadPoolExecutor (8 workers / 16 in-flight operations) with bounded admission. Cancellation waits for already-running synchronous work to finish before propagating, preventing a late DB commit from racing an assumed release. Chat, stream finalization, readiness, Redis/cache, HTTP audit, request lookup and admin DB operations are routed through it. PostgreSQL connect/statement/lock/idle-transaction limits and Redis socket timeouts were bounded. Non-stream finalization now reuses the existing receipt-backed atomic finalization repository path.

This protects updated request paths from direct synchronous DB/Redis calls on the event loop. It cannot kill a blocked driver thread or guarantee a hard deadline if OS/network I/O fails outside driver timeouts.

## Results

- Full pytest: 193 passed in 18.22s. Pytest printed branch-aware coverage 79.92%, below the configured 80% threshold; therefore pytest+coverage gate is **not passed** despite process exit 0.
- Integration-inclusive coverage: 85.72% when merging pytest plus actual PostgreSQL, Redis adapter and two-replica probe coverage. Supplementary evidence; it does not erase pytest-only threshold failure.
- PostgreSQL integration probe: PASS for tested cold-start budget contention, caps, idempotent/atomic finalization, commit-unknown receipt recovery, audit rollback and orphan reconciliation.
- Redis adapter probe: PASS for global limit, shared cache, singleflight/lease behavior and failure policies.
- Two-replica probe: PASS for shared Redis behavior and shared PostgreSQL budget/audit state.
- Real TCP outage matrix: **FAILED**. 20 concurrent requests during PG stop; `/live` 200 at 1.547s; max request 9.594s; `/ready` unavailable by 3.172s harness boundary; recovery readiness 200. Some requests timed out/returned errors; reservation count stayed zero for injected requests; audit writes were visible after recovery. This misses proposed 1s liveness, 2s readiness and 5s dependent-request targets.
- Normal SSE and client disconnect: PASS in staging; disconnect ended with settled reservation and cancelled provider attempt. Injected finalization failure returned `stream_finalization_unknown`, left reservation reserved and had no receipt/request audit, a conservative state that still needs operational reconciliation proof.
- SIGTERM: PASS for one in-flight synthetic stream; process exit 0, one audit, settled reservation, readiness 200 after restart.
- Backup/restore: PASS for isolated synthetic PostgreSQL. Fresh DB matched 14 attempts, 16 receipts, 29 request logs and 18 reservations, then accepted a write smoke. End-to-end took 2.114s locally; not a production RPO/RTO commitment.

Raw records: `staging-acceptance-final.json`, `postgres-integration-covered.json`, `redis-adapter-covered.json`, `redis-two-replica-covered.json`, `pg-backup-restore-result.json`, `pytest-final.log`, and associated exit-code files.

## Required P1 follow-up

Implement DB-outage admission/circuit fast-fail and queue/connection-pool instrumentation, then repeat 20–50 TCP concurrency outage runs. Require durable-state assertions for every injection point, including reserve/settle/commit-unknown, crash/restart reconciliation and audit/attempt uniqueness. Current code is not sufficient for Wave 4 release acceptance.
