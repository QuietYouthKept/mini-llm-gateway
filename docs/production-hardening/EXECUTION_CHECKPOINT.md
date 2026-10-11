# Execution checkpoint

Updated: 2026-10-11 04:58 UTC (2026-10-11 Asia/Shanghai)

## Current phase

Phase 1 targeted PostgreSQL lock-timeout correctness review is locally validated; Phase 2 commit/remote CI is next.

## Protected identity

- Branch: `codex/p0-p1-production-hardening`
- Base/HEAD: `4d067cc2bdd137218ad055e15bfaf85b1078644f`
- HEAD tree: `e6112a8b5b161cd632f6216799959c443ab1b42d`
- Initial worktree before prior wave: clean; the external checkpoint captured four modified tracked files and four untracked files. Phase 1 added three tracked changes and two diagnostic scripts since that snapshot; the original binary diff and copied files remain intact.
- Existing dataset-evaluation worktree: preserved with its 19 pre-existing dirty paths
- External evidence root: `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z`
- New Wave 2 evidence root: `E:\project-test-assets\01-gateway\results\production-hardening-wave2-20261011T045752Z`
- Exact tracked binary diff, untracked copies and hashes: `00-checkpoint\` under the new evidence root.
- Checkpoint capture: `00-checkpoint\git-state.json`; tracked diff length 10,334 bytes; four untracked files copied and SHA-256 hashed.

## Completed

- Rechecked remote branch SHA and GitHub Run `38070902799` against the specified baseline.
- Verified the existing authorized SSH identity resolves to `QuietYouthKept`.
- Checked target path and branch were absent before creating the isolated worktree.
- Captured source manifest, lock/Dockerfile hashes, Docker version/resources, running-container inventory, host memory/disk, WSL, and proxy-port reachability.
- Recorded the inherited capacity failure and missing failure-time database evidence without upgrading hypotheses to root cause.
- Created an isolated PostgreSQL 16 + Redis 7 + Gateway Compose project and captured live activity, lock waits, persistence state, and server logs under the external evidence root.
- Reproduced a bounded same-client advisory-lock timeout: 8/8 requests returned 503 with PostgreSQL SQLSTATE `55P03`, `Lock:advisory` waits, and blocker PID evidence.
- Confirmed a process-wide database-circuit side effect: the first cross-client control after the injected timeout was rejected while the DB circuit remained open. After restarting only the isolated Gateway (database retained), that control returned 8/8 success with normal settlement state.
- Added a scoped `database_lock_timeout` error, excluded PostgreSQL `55P03` from the global DB circuit, retained receipt lookup before classifying finalization failures, and added durable request auditing for lock-timeout paths.
- Rebuilt the final-source candidate image through the user-confirmed proxy `7890`; image ID/digest is recorded in `gateway-image-final-identity.txt`. Injected the lock while alternating two synthetic client keys: 4/4 blocked-client requests returned `503 database_lock_timeout` with error audit rows; 4/4 other-client requests returned 200 with settled reservations, receipts, and attempts. An immediate same-process post-lock batch returned 8/8 success.
- Final-source 20/50 concurrent TCP lock-contention probes completed: all 20/50 requests had durable error audit rows, no reservation/receipt/attempt; response classification was respectively 8 lock-timeout + 12 admission-overloaded, and 8 lock-timeout + 42 admission-overloaded. `/live` and `/ready` remained HTTP 200, with max sampled latency 91.36ms and 72.77ms.
- Ran a separate graceful stop/start of only the isolated PostgreSQL container. While offline: c20 returned 8 `database_unavailable` + 12 admission-overloaded; c50 returned 50 `database_unavailable`. After restart, both outage batches had zero audit/reservation/receipt/attempt rows; `/ready` returned 200 and a same-process recovery batch succeeded 8/8. Two expired reservations left by the PG rollback probe were snapshotted, then reconciled to released with lease-expiry audits/receipts. Final totals: 364 settled, 3 released, 0 reserved.
- Baseline clean-HEAD checks: Ruff and compileall passed; pytest-only 209 passed, 1 skipped; combined coverage 81.37%, independent 80% gate passed. Two new focused lock-timeout tests pass with the related streaming failure suite (35 passed total).
- Candidate final local gates: Ruff and compileall passed; full pytest 211 passed, 1 skipped; branch-aware total coverage 80.93%; independent `coverage report --fail-under=80` passed. Functional Eval 7/7 and Security Eval 8/8 passed.
- PostgreSQL integration probe passed (including cold concurrent reserve, audit rollback, commit-ack-loss receipt recovery, idempotent replay, lease expiry/reconciliation). Redis adapter probe and two-replica Redis/PostgreSQL shared-budget probe both passed.
- Secret scan and `git diff --check` passed. Provider contract and TCP SSE E2E are included in the 211-test pytest run.
- Container runtime checks passed: UID/GID `10001:10001`, read-only rootfs, dropped all Linux capabilities, `no-new-privileges`, `/app` write denied, `/tmp` write succeeded, healthcheck healthy, SIGTERM exited with code 0 and Gateway restarted healthy.
- One identical no-cache rebuild did not reproduce the candidate image: final image `sha256:42935410d1bee19ec864c038b092091f1c9b9f94673deae5f30491aafcad4072`; repeat `sha256:e208f0eff6da841b929ce620027a10cc374be621f5948facc0272fd1076b43d6`. First five rootfs layers match; the next five differ. The reproducibility gate is FAILED; no further image/base changes were attempted.
- Docker Scout CVE scan is BLOCKED because the installed CLI requires Docker Hub login. Trivy, Grype, and Syft are not installed. No vulnerability-free or SBOM claim is made.
- Re-audited the E worktree and preserved its current tracked/untracked state outside Git before running new tests. Confirmed local proxy TCP port 7890 is reachable; did not alter proxy/TLS settings.
- Reproduced finalization row-lock contention over real TCP/SSE on current source: partial output followed by `database_lock_timeout`; the first snapshot showed one `reserved` reservation with no receipt or request audit. Fixed this by avoiding a second settlement attempt, persisting one `accounting_failed` audit with `usage_source=unsettled`, and allowing lease reconciliation to release the reservation.
- Updated PostgreSQL lease reconciliation to update an existing request audit row rather than inserting a second row. After preserving the before-reconciliation snapshot, the exact two expired synthetic stream-probe reservations were reconciled; each ended `released` with one release receipt and one audit. Current-source request preserved its successful Provider attempt and original lock-timeout message.
- Added focused regressions for nested SQLSTATE in both cause and context chains and for no second stream settlement on definite `55P03`.
- Final current-worktree local gates: Ruff 0, compileall 0, pytest 212 passed/1 skipped (0), coverage fail-under-80 (0), Functional Eval 7/7 (0), Security Eval 8/8 (0), Secret Scan 0, `git diff --check` 0. Coverage: 83.83% statements; 68.06% branch-only (618/908); 80.97% coverage.py combined.
- PostgreSQL repository integration, including cold concurrent admission, atomic audit rollback, replay, lease reconciliation and TCP Commit ACK loss: exit 0. Redis adapter and two-instance PostgreSQL/Redis probes: both exit 0.

## Not yet executed

- GitHub Actions/Artifact verification, commit/push, and final review.
- Docker vulnerability scan and SBOM generation remain blocked pending an authorized scanner/authenticated environment.
- Formal 36-cell capacity experiment; image scan/reproducibility evaluation; SSRF/egress tests; HA/backup/restore drill; alert delivery and observability end-to-end; SSE fault matrix.
- New-branch commit, push, CI run, and Artifact validation.

## Evidence paths and interpretation

- External evidence root: `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z`
- Lock evidence: `pg-diagnostic\induced-lock-55p03.json`, `induced-lock-cross-client-restarted.json`, `induced-lock-55p03-fixed-mixed-clients.json`, and `post-lock-same-process-recovery.json`, with adjacent `.log` and `.exitcode` files.
- PostgreSQL server-side SQLSTATE/wait evidence: `pg-diagnostic\induced-lock-55p03-postgres-log-extract.txt` and `pg-diagnostic\postgres-live-logs-after-minimal-matrix.txt`.
- The injected `55P03` mechanism is reproduced and fixed in the candidate; this is not proof of the historical overnight 1,984/1,984 failures, because that run lacks contemporaneous SQLSTATE, blocker, and wait snapshots.
- Prior short normal-concurrency tests passed but are not a formal capacity matrix or throughput claim.
- Pytest-only branch coverage is 80.93%; PostgreSQL repository itself is 17%, connection module 44%, Redis prompt-cache/rate-limiter adapters 0%, and Redis singleflight 22% in the pytest-only coverage report. Separate PostgreSQL/Redis integration probes passed but were not merged into pytest coverage. Treat this as a residual coverage gap, not as fully covered repository code.
- Historical overnight database-failure cause remains unknown despite the reproduced `55P03`/global-circuit defect. Database outage verification used graceful stop/start, not SIGKILL or failover.
- Current worktree and candidate image are not committed. The image must not be treated as a commit-bound release artifact; commit/CI/Evidence binding is still pending and was not attempted with mandatory release gates failed/blocked.

## Stop conditions

Stop the affected experiment immediately for duplicate receipt/charge, unknown database state, unbounded resource growth, interference with unrelated containers, or any chance of paid provider traffic. Preserve raw logs and database snapshots before any reconciliation. Do not expand to capacity cells until correctness and resource safety are demonstrated.
