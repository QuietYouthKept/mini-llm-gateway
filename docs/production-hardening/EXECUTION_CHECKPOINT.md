# Execution checkpoint

Updated: 2026-10-11 05:40 UTC (2026-10-11 Asia/Shanghai)

## Current phase

The PostgreSQL lock-timeout fix and evidence documentation are committed and passed remote CI. The candidate built from `3a06d06198757f1eeb306b7d8d2e0d46e842df25` now has independently verified reproducible OCI output, a fresh vulnerability scan/SBOM, and a restricted-runtime smoke test. Production acceptance remains blocked by 44 High findings and the unexecuted release gates listed below.

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
- The earlier default image rebuild comparison produced image IDs `sha256:42935410d1bee19ec864c038b092091f1c9b9f94673deae5f30491aafcad4072` and `sha256:e208f0eff6da841b929ce620027a10cc374be621f5948facc0272fd1076b43d6`. Inspection of the actual layer tar members established timestamp-only differences: generated account-file mtimes in layer 6, `.venv` entry mtimes in layer 7, and directory mtimes in layers 8–10. This is the measured cause for those image differences.
- Two independent, no-cache Buildx OCI exports of the exact `3a06d06` source, using `SOURCE_DATE_EPOCH=1791695795` and exporter option `rewrite-timestamp=true`, were byte-identical (61,011,456 bytes; SHA-256 `1946fbc7ed4ef7574efddd4eaa23e837137720d84027a6a15842a5ff31f255f7`). Independent OCI parsing also found identical index, manifest, config, all 10 layer descriptors, and rootfs diff IDs. The scoped OCI reproducibility check therefore PASSES for this exact build command and platform; this does not establish every Docker/Compose or other-platform build path as reproducible.
- A current-source image scan used the official Trivy v0.75.0 Windows release binary after matching its SHA-256 against the official release checksum (`4e43bd71a30f51aee39525f60f2b47043af77eb8df8fe082aae4372b69c6660f`). Fresh vulnerability DB download succeeded at `2026-10-11T05:36:05Z`. Scan results: 172 findings (44 High, 63 Medium, 62 Low, 3 Unknown); CycloneDX 1.7 SBOM contains 128 components. The earlier v0.74.0 scan returned the same counts and is retained. Security release gate remains FAILED pending review/remediation of High findings; no “zero vulnerabilities” claim is made.
- The loaded image `sha256:eb587db5331fdd4f13bd579344a38a8c2839c5c98f42b9f47a4ff31f561b70d2` passed a current-source runtime smoke: UID/GID `10001:10001`, read-only rootfs, all capabilities dropped, `no-new-privileges`, `/app` write denied while `/tmp` and `/app/data` tmpfs writes succeeded, `/live` HTTP 200, Docker health `healthy`, and graceful `docker stop --timeout 10` exit code 0. This was a local SQLite smoke, not PostgreSQL/Redis staging, migration, upgrade, rollback, or disaster-recovery acceptance.
- Re-audited the E worktree and preserved its current tracked/untracked state outside Git before running new tests. Confirmed local proxy TCP port 7890 is reachable; did not alter proxy/TLS settings.
- Reproduced finalization row-lock contention over real TCP/SSE on current source: partial output followed by `database_lock_timeout`; the first snapshot showed one `reserved` reservation with no receipt or request audit. Fixed this by avoiding a second settlement attempt, persisting one `accounting_failed` audit with `usage_source=unsettled`, and allowing lease reconciliation to release the reservation.
- Updated PostgreSQL lease reconciliation to update an existing request audit row rather than inserting a second row. After preserving the before-reconciliation snapshot, the exact two expired synthetic stream-probe reservations were reconciled; each ended `released` with one release receipt and one audit. Current-source request preserved its successful Provider attempt and original lock-timeout message.
- Added focused regressions for nested SQLSTATE in both cause and context chains and for no second stream settlement on definite `55P03`.
- Final current-worktree local gates: Ruff 0, compileall 0, pytest 212 passed/1 skipped (0), coverage fail-under-80 (0), Functional Eval 7/7 (0), Security Eval 8/8 (0), Secret Scan 0, `git diff --check` 0. Coverage: 83.83% statements; 68.06% branch-only (618/908); 80.97% coverage.py combined.
- PostgreSQL repository integration, including cold concurrent admission, atomic audit rollback, replay, lease reconciliation and TCP Commit ACK loss: exit 0. Redis adapter and two-instance PostgreSQL/Redis probes: both exit 0.

## Not yet executed

- GitHub Actions/Artifact verification, commit/push, and final review.
- Formal 36-cell capacity experiment; SSRF/egress tests; HA/backup/restore drill; alert delivery and observability end-to-end; full SSE fault matrix.
- PostgreSQL/Redis production-like staging, migration repeatability, upgrade/rollback and dependency-failure recovery against this exact candidate image.
- Triage and remediation of the 44 High image findings, followed by a fresh scan of a source-identified rebuilt image.
- The code and evidence-document commits are already pushed and their GitHub CI/Evidence Artifacts were verified; the most recent published SHA before the current new evidence-document update is `3a06d06198757f1eeb306b7d8d2e0d46e842df25`.

## Evidence paths and interpretation

- External evidence root: `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z`
- Lock evidence: `pg-diagnostic\induced-lock-55p03.json`, `induced-lock-cross-client-restarted.json`, `induced-lock-55p03-fixed-mixed-clients.json`, and `post-lock-same-process-recovery.json`, with adjacent `.log` and `.exitcode` files.
- PostgreSQL server-side SQLSTATE/wait evidence: `pg-diagnostic\induced-lock-55p03-postgres-log-extract.txt` and `pg-diagnostic\postgres-live-logs-after-minimal-matrix.txt`.
- The injected `55P03` mechanism is reproduced and fixed in the candidate; this is not proof of the historical overnight 1,984/1,984 failures, because that run lacks contemporaneous SQLSTATE, blocker, and wait snapshots.
- Prior short normal-concurrency tests passed but are not a formal capacity matrix or throughput claim.
- Pytest-only branch coverage is 80.93%; PostgreSQL repository itself is 17%, connection module 44%, Redis prompt-cache/rate-limiter adapters 0%, and Redis singleflight 22% in the pytest-only coverage report. Separate PostgreSQL/Redis integration probes passed but were not merged into pytest coverage. Treat this as a residual coverage gap, not as fully covered repository code.
- Historical overnight database-failure cause remains unknown despite the reproduced `55P03`/global-circuit defect. Database outage verification used graceful stop/start, not SIGKILL or failover.
- The candidate OCI evidence is source-bound to commit `3a06d06198757f1eeb306b7d8d2e0d46e842df25`; its manifest/config/layers are independently identified in the external evidence report. It is not a production release artifact: the 44 High findings and remaining gates still block production acceptance.

## Current-source image evidence addendum (2026-10-11)

- OCI identity comparison: `E:\project-test-assets\01-gateway\results\production-hardening-wave2-20261011T045752Z\03-docker-reproducibility\candidate-oci-identity-comparison.json`.
- Final Trivy v0.75.0 JSON, CycloneDX SBOM, logs and exit codes: the same directory, files `candidate-trivy-0.75-vuln.json`, `candidate-sbom-0.75.cdx.json`, `candidate-scan-summary-0.75.json`, and corresponding `.log`/`.exitcode` files. Earlier v0.74.0 outputs are retained separately.
- Runtime and read-only permission evidence: `candidate-runtime-check.json`, `candidate-runtime.log`, and `readonly-permission-probe-verified.json` in that directory.
- Trivy v0.75.0 checksum, official latest-release API metadata, and download record are retained alongside the scan. Docker Hub image pulls returned EOF; this did not block the checksum-verified Windows binary scan via proxy port 7890.
- Results are explicitly scanner/database-version-bound and not asserted to remain the latest indefinitely.

## Stop conditions

Stop the affected experiment immediately for duplicate receipt/charge, unknown database state, unbounded resource growth, interference with unrelated containers, or any chance of paid provider traffic. Preserve raw logs and database snapshots before any reconciliation. Do not expand to capacity cells until correctness and resource safety are demonstrated.
