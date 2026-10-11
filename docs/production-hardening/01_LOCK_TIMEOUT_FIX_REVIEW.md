# Phase 1 — PostgreSQL lock-timeout correctness review

## Scope and source identity

- Tested source base: `4d067cc2bdd137218ad055e15bfaf85b1078644f` plus the scoped change now committed as `ae1171ffb09704b6dbacfe1c7f18144a6e4168bb`.
- External evidence: `E:\project-test-assets\01-gateway\results\production-hardening-wave2-20261011T045752Z\01-lock-timeout\`.
- Runtime evidence used an isolated PostgreSQL 16 database and synthetic local mock providers. No paid Provider was called.

## Change under review

- PostgreSQL SQLSTATE `55P03` is now request-scoped, including nested `__cause__` and `__context__` paths. It maps to retryable `database_lock_timeout` and does not open the process-wide database dependency circuit. Connection errors continue to use dependency-failure handling.
- Synchronous chat and stream admission record a durable error audit when the database remains available.
- A stream finalization whose receipt lookup completes without a matching receipt is treated as a definite lock timeout. It does not enter a second settlement attempt from the exception path. The live stream emits an SSE error event; an `accounting_failed` audit marks usage `unsettled`, with no fabricated billable tokens or `budget_after`.
- The reservation remains `reserved` until lease expiry. The reconciler releases it with a durable release receipt. When an accounting-failure audit already exists, reconciliation updates that same unique request row and preserves prior error information rather than inserting a conflicting second request audit.

## Executed tests and observed outcomes

- Focused unit + TCP streaming tests: 15 passed (initial baseline capture).
- Focused blocking-I/O and streaming-failure regressions after the fix: 36 passed.
- Full pytest with branch measurement: 212 passed, 1 skipped; exit code 0.
- Coverage gate: exit code 0 at 80.97% coverage.py combined. Statement coverage was 83.83%; branch-only coverage was 68.06% (618/908 branches). This is not a claim of 80.97% branch-only coverage.
- Functional Eval: 7/7; Security Eval: 8/8; Ruff, compileall, Secret Scan and `git diff --check`: exit code 0.
- PostgreSQL integration probe: exit code 0. It exercised cold concurrent budget admission, transactional audit rollback, idempotent/replayed finalization, lease expiry, and TCP Commit ACK loss with receipt recovery. Raw output is `05-postgres-diagnosis\integration-probe.log`.
- Redis adapter probe and two-instance Redis/PostgreSQL probe: both exit code 0. They exercised shared cache/rate limits, outage behavior, singleflight lease expiry/fencing, and cross-instance budget consistency.
- Real TCP/SSE advisory-lock admission probe on the candidate image: same-client stream returned `503 database_lock_timeout`; the different-client stream returned 200 and persisted a settled reservation, one settlement receipt, one success audit and one successful attempt. See `real-pg-stream-lock-rerun.log`.
- Real TCP/SSE finalization row-lock injection on current source: four message events were delivered, then the server sent `event: error` with `database_lock_timeout`. The first captured failed state had one `reserved` reservation and no receipt. After lease expiry, exact pre-reconciliation snapshots were saved; reconciliation handled only the two expired synthetic probe reservations. The current-source request retained exactly one audit (`orphaned_released`, `reservation_lease_expired`, `usage_source=not_billed`), one release receipt, and its successful Provider attempt. Evidence: `real-pg-source-finalization-lock.log`, `expired-before-reconcile.json`, and `reconciled-accounting-verification.json`.

The finalization-lock scenario is a failure-path validation, not a claim that content already sent to a client is billable. The present policy releases the reservation without charging after the settlement transaction definitively fails and the lease expires. Whether product policy requires durable later billing of emitted content needs an explicit accounting contract; no uncommitted usage or budget balance was invented.

## Boundaries / remaining validation

- These results are local to the current uncommitted worktree and disposable infrastructure. No current-commit GitHub Actions run or Artifact has been verified yet.
- This is an injected advisory/row-lock test plus graceful PostgreSQL restart evidence from the prior run. It is not proof of the historical 1,984-request failure's root cause, PostgreSQL SIGKILL recovery, or HA failover.
- Pytest-only PostgreSQL repository coverage remains low; actual integration probes are separate evidence and have not been merged into coverage totals. Coverage report under `13-coverage\` reports the exact module totals.
- `database_lock_timeout` is currently HTTP 503 by contract. No capacity/RPS/SLO claim is made from these probes.

## Phase result

**Targeted lock-timeout change: remote CI verified.** The code is committed as `ae1171ffb09704b6dbacfe1c7f18144a6e4168bb` and GitHub Actions Run [38114074579](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38114074579) completed successfully for that exact SHA. The Linux run reports 213 passed, independent coverage gate exit 0, and 83.99% coverage.py combined. Evidence Artifact `11692432765` and validation Artifact `11693170566` were downloaded; Manifest expected/actual count was 155/155, missing/extra/hash-or-size mismatches were all zero, and the manifest SHA-256 was `5ebf56d575088e7960bf8fd172fba251621b3de51323a5420aa126f8d02475f2`. Local independent validation is recorded in `02-ci\download\manual-manifest-verification.json`.

This verifies the focused change's current commit through CI and the attached artifact integrity. It does not establish overall release readiness. The broader release remains blocked/partial on reproducible Docker build, current-image CVE/SBOM disposition, historical-outage diagnosis, formal capacity matrix, SSRF/egress, and release/rollback/observability criteria.
