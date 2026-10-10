# Overnight Engineering & Benchmark Sprint — Final Report

**As of:** 2026-10-10 17:01 UTC
**Workspace:** `E:\mini-llm-gateway-dataset-eval`
**Branch:** `codex/dataset-evaluation`
**Base source commit:** `9fd1cdca5318a8b00e52b1a29176b7bd5fc66b77`
**Overall:** `PARTIAL` — engineering fixes and local gates are verified; capacity matrix stopped at its correctness guard; remote CI/artifact and 32/64 concurrency remain outstanding.

## A. What completed, failed, and remains blocked

### PASS

- Reproduced why GitHub run `38043507409` could hang: in a Linux container, the PostgreSQL COMMIT-ACK-loss test left the main thread in psycopg `commit()` and the proxy relay thread in blocking `recv()`. Closing a socket from another thread did not reliably interrupt `recv()` on Linux. Added socket/accept deadlines, socket `shutdown()` before close, bounded thread joins, and explicit thread-stopped assertions.
- Hardened CI against indefinite waits: 45-minute job deadline, 20-minute pytest deadline, live `tee` output with reliable `PIPESTATUS` capture, faulthandler timeout, and separate pytest/coverage exit files. Locked workflow sync includes the `datasets` extra imported by the preserved quality audit tests. Corrected the step label to say “coverage gate”; the 80% gate is coverage.py combined coverage, not branch-only coverage.
- Current dirty-worktree tests passed on disposable Linux/Python 3.11 (214 passed, 49.91 s, combined coverage 84.15%) and final Windows/Python 3.11 (214 passed, 22.77 s). Windows coverage: statements 86.79%, branches 71.28%, combined 84.02%; independent `coverage report --fail-under=80` passed. These are local runs; no new GitHub result yet.
- Final Windows checks all returned exit code 0: Ruff, compileall, complete pytest, coverage gate, Functional Eval (7/7), Security Eval (8/8), Provider Contract (13 tests), Uvicorn TCP SSE (2 tests), tracked-file secret scan, and `git diff --check`.
- Real Redis adapter and two-replica probes passed. PostgreSQL integration probe passed, including Commit-Unknown receipt recovery, replay idempotency, audit rollback, concurrent finalization, and orphan reconciliation.
- Current-source container built successfully (local image ID below), ran as UID/GID 10001, root filesystem was read-only (write attempt rejected), two migration invocations succeeded, readiness returned 200 after recovery, and SIGTERM stop exited 0 without OOM.
- SBOM generated; Trivy scan exited 0; pip-audit exited 0 with no known dependency vulnerabilities (editable project skipped).

### PARTIAL / FAILED

- Fixed-resource capacity matrix: 12/36 cells. Concurrency 1 completed 9/9 cells at 100% success. At concurrency 8, two cells passed; the third returned 1,984/1,984 `database_unavailable` 503 responses. The invariant stop rule halted further load. Two expired reservations were reconciled to `released`; final persisted state has no `reserved` or `uncertain` reservations and no duplicate request receipt. The matrix is not a complete capacity acceptance.
- Image scan found 26 vulnerabilities from the image SBOM: Critical 0, High 4, Medium 9, Low 13. Trivy warned that a third-party SBOM may cause inaccurate detection. Do not say “no vulnerabilities”.
- No capacity bottleneck optimization or fair A/B experiment completed. Performance improvement is not verified.
- Concurrency 32 and 64 were not run. Their success rate, RPS and latency are unknown.

### BLOCKED

- GitHub Actions for the new code has not run. The historical run was canceled after it remained in Full pytest for hours; a canceled run did not provide downloadable job logs. New remote run and artifact remain pending commit/push and verification.
- Root cause of the 8-concurrency PostgreSQL failure is unconfirmed. Same-client advisory-lock contention plus short lock/statement deadlines is a plausible hypothesis, not proven without SQLSTATE/wait-event capture at failure time.
- Human semantic privacy review of the pre-existing dataset samples has not been completed. The sample files and old dataset results remain local and are not part of the new commit.

## B. Git and workspace

- Branch: `codex/dataset-evaluation`.
- Source HEAD before sprint edits: `9fd1cdca5318a8b00e52b1a29176b7bd5fc66b77`; base tree `35f30af4dafce3bf9db78b8609a550117eeb60e7`.
- Initial 19 pre-existing uncommitted paths were fingerprinted outside the repository and preserved. The data roots and historical workspaces were not altered.
- Sprint source changes: `.github/workflows/ci.yml`, `scripts/postgres_commit_ack_loss_probe.py`, and `Dockerfile`. New reports: this file plus `13_POSTGRES_REDIS_CAPACITY.md`, `14_RESUME_IMPACT_REPORT.md`, and the execution checkpoint. The pre-existing dataset harness/report files remain untouched and unstaged.
- Source fix commit: `ffc179fe25f31b9f3a2475f5daf14e7ddf10bfe0` (`fix: bound postgres commit-ack probe and CI tests`). This report and supporting reports/checkpoint are being committed separately. Remote branch `codex/dataset-evaluation` was absent at pre-push inspection. SSH 443 currently authenticates as `yqia0089-bot`; GitHub CLI has `QuietYouthKept` active with `repo`/`workflow` scopes. If pushed, use that existing HTTPS credential path and do not alter SSH configuration.
- No force push, reset, clean, merge, or tag was performed.
- Raw evidence, including logs, test XML, coverage output, per-cell metrics, database snapshots, SBOM, scan, image build logs, and hashes, is outside Git at `E:\project-test-assets\01-gateway\results\overnight-sprint-20261010T155645Z\`.

## C. Tests and security gates

| Gate | Result | Exact evidence |
|---|---|---|
| Ruff | PASS, exit 0 | `junit-coverage/ruff-attempt2.log` |
| compileall | PASS, exit 0 | `junit-coverage/compileall-attempt2.log` |
| Complete pytest | PASS, 214 passed in 22.77 s, exit 0 | `junit-coverage/pytest-attempt2.log`, `pytest-junit.xml` |
| Coverage.py gate | PASS, `--fail-under=80`, exit 0 | `junit-coverage/coverage-gate-attempt2.log` |
| Statement coverage | 86.79% (3,495 / 4,027 statements) | `junit-coverage/coverage.json` |
| Branch-only coverage | 71.28% (623 / 874 branches) | `junit-coverage/coverage.json` |
| Combined coverage.py | 84.02% | `junit-coverage/coverage.json` |
| Functional Eval | PASS 7/7, exit 0 | `junit-coverage/functional-eval-attempt2.log` |
| Security Eval | PASS 8/8, exit 0 | `junit-coverage/security-eval-attempt2.log` |
| Provider Contract | PASS 13 tests, exit 0 | `junit-coverage/provider-contract-attempt2.log` |
| TCP SSE | PASS 2 tests, exit 0 | `junit-coverage/http-sse-e2e-attempt2.log` |
| PostgreSQL live integration | PASS, exit 0 | `database-invariants/postgres-final-probe.log` |
| Redis adapter | PASS, exit 0 | `provider-faults/redis-adapter-probe.log` |
| Redis two-replica | PASS, exit 0 | `provider-faults/redis-two-replica-probe.log` |
| Secret scan | PASS, exit 0; scans tracked files only | `junit-coverage/secret-scan-attempt2.log` |
| `git diff --check` | PASS, exit 0 | `junit-coverage/diff-check-attempt2.log` |
| Dependency audit | PASS, pip-audit exit 0, no known vulnerabilities | `security/pip-audit.json` |
| Image scan | PARTIAL: Trivy exit 0; 4 High findings; SBOM caveat | `security/trivy-v0.74.0/scan-summary.json`, full scan JSON |

The initial PowerShell wrapper attempt failed to invoke pytest/Evals correctly and is retained as `pytest-wrapper-error-attempt1.log` with its exit summary. The corrected attempt 2 above is the actual final local test run. It is not presented as a project-code test failure.

## D. Capacity and performance

Completed cell details and environment constraints are in [13_POSTGRES_REDIS_CAPACITY.md](13_POSTGRES_REDIS_CAPACITY.md). Concurrency 1 showed 100% success across 9 completed runs with target cache ratios 0/0.5/0.9; concurrency 8 had two 100% cells then one complete database-unavailable failure. Matrix stop: 12/36. Concurrency 32/64: not executed. P95/P99 for the failed cell describe error responses only.

No A/B optimization was performed, so `PERFORMANCE_IMPROVEMENT_VERIFIED=FALSE`. The experiment demonstrates a reliability boundary and a test stop/recovery procedure, not Gateway capacity.

## E. Database and Redis consistency

- Post-load, post-reconciliation database snapshot: 3,565 reservations (3,563 `settled`, 2 `released`, 0 `reserved`, 0 `uncertain`); 3,565 `stream_finalizations`; 0 duplicate finalization request IDs; 4,132 audits; 3,563 provider attempts. The two orphan releases each have reconciliation audit entries and no provider attempt. Usage remained 297,670 tokens.
- Real Commit-ACK-loss probe: COMMIT command completed on the wire, client saw `psycopg.OperationalError`, direct receipt recovery succeeded, replay was idempotent, reservation stayed settled, usage 12 tokens, one audit, one attempt; both proxy threads stopped.
- Redis adapter: 20 requests, 10 admitted / 10 rejected; exact shared cache; lease expiration/recovery; stale-owner fencing; fail-open/fail-closed error contract all passed.
- Two Uvicorn replicas: distributed singleflight executed provider once and returned equivalent 200 responses; shared rate limit/cache behaved consistently; PostgreSQL shared-budget race returned one 200 and one 429, one settled reservation, two audit rows, one provider attempt.
- Database correctness after explicit reconciliation passed the final-state oracle. Because the two expired reservations triggered the matrix stop, the full load-time invariant gate is **PARTIAL**, not an unqualified pass.

## F. CI, image, and container status

- The Linux hang root cause is identified and patched as described above. New Linux local run passed 214 tests after the fix. Remote CI has not verified the commit yet.
- Current-source image ID: `sha256:c5712bf1ccb8871840c5ec6cad10c9e28b96e057bccced636380f3e17279ee34`. This is a local Docker image ID, not a registry digest.
- Explicit migration ran twice successfully. Readiness probes returned 200 after the configured dependency recovery window. Rootfs write attempt failed with “Read-only file system”. Gateway ran as UID 10001. `docker stop --timeout 10` ended with container exit 0 and no OOM.
- SBOM is at `image-build/current-image-sbom.cdx.json`. Trivy 0.74.0 scan used the CycloneDX SBOM; it returned 26 vulnerabilities (0 Critical, 4 High, 9 Medium, 13 Low) with a third-party SBOM accuracy warning. Docker Scout was unavailable without Docker ID login; no Scout result is claimed.
- `REMOTE_CI_PASS` and `EVIDENCE_ARTIFACT_VERIFIED` remain BLOCKED until the new pushed commit's workflow and uploaded artifact are checked.

## G. Four strongest evidence-backed resume bullets

1. **Linux CI/reliability:** Reproduced a PostgreSQL COMMIT-ACK proxy hang caused by blocked `recv()` surviving cross-thread close; implemented bounded socket shutdown/thread lifecycle and verified current-source Linux full suite (214 passed). Source: `scripts/postgres_commit_ack_loss_probe.py`; evidence: Linux pytest log.
2. **Idempotent accounting:** Injected a real post-COMMIT acknowledgement loss; recovered a durable receipt and replayed safely with one 12-token settlement, one audit and one provider attempt. Source: PostgreSQL probe scripts; evidence: `database-invariants/postgres-final-probe.log`.
3. **Multi-instance Redis:** Verified shared rate limit/cache and distributed singleflight across two Uvicorn processes; 20 concurrent requests split 10 admitted/10 rejected and identical concurrent cache misses caused one synthetic provider execution. Evidence: Redis probe logs.
4. **Failure-safe capacity testing:** Added database-state stop/reconciliation to a fixed-resource benchmark; stopped at the first all-503 database failure and reconciled two expired reservations to released with no duplicate receipt or usage charge. Source/evidence: `13_POSTGRES_REDIS_CAPACITY.md` and database snapshot JSON.

Do not add an “X% performance improvement” bullet. The historical public dataset result is local Mock Provider/SQLite and was not rerun in this sprint; human semantic privacy review is still pending. Additional role-specific Chinese and English bullet variants are in [14_RESUME_IMPACT_REPORT.md](14_RESUME_IMPACT_REPORT.md).

## H. Ten likely senior-interviewer questions and concise answers

1. **Why did `close()` not unblock `recv()`?** On Linux, descriptor close from another thread is not a reliable cancellation mechanism for an in-progress blocking socket syscall. The fix explicitly calls `shutdown(SHUT_RDWR)`, sets finite deadlines, and bounds joins.
2. **How do you know COMMIT actually happened if the client saw an error?** The fault proxy observed COMMIT `CommandComplete` before dropping the following `ReadyForQuery`; after reconnect, the repository queried the unique durable receipt and recovered the committed result.
3. **Why not retry settlement immediately?** The client error describes acknowledgement uncertainty, not transaction rollback. Blind replay can double-charge unless the operation is keyed/idempotent; query the durable receipt first and reconcile only when state remains unresolved.
4. **What does the receipt prove?** It provides a durable unique terminal record tied to reservation/request identity and lets a retry resolve commit-unknown without repeating usage mutation. The fault experiment checks one receipt, one audit and one provider attempt.
5. **Why did the capacity matrix stop?** It found two expired reservations after an 8-concurrency cell; correctness takes priority over collecting more latency points. Reconciliation released the orphans, then no further load was sent to that DB.
6. **Is concurrency 8 capacity 23 RPS?** No. Two cells reached 17.17 and 23.10 RPS at 100%, but the third returned only 503 and the matrix stopped. This is a censored experiment, not a capacity limit or SLO.
7. **Why is 84.02% not branch coverage?** Coverage.py's combined percentage includes statements and branches. The same JSON reports statement 86.79% and branch-only 71.28%; the CI gate is explicitly labeled combined coverage.
8. **What caused the all-503 cell?** It is not proven. Same-client advisory-lock serialization interacting with lock/statement timeout and broad database-unavailable classification is plausible; failure-time SQLSTATE and PostgreSQL wait events are missing.
9. **What does the Redis singleflight test establish?** The two real app processes coordinate through Redis for this deterministic test: both callers receive equivalent results while the provider runs once; lease expiry permits recovery and a stale owner cannot release the new lease.
10. **Is this release-ready?** No. Remote CI/artifact are unverified, 32/64 and 24 matrix cells were not run, PostgreSQL failure diagnosis remains open, and the image has four High scan findings plus SBOM caveat.

## I. Remaining problems and exact state

| Output | State | Reason |
|---|---|---|
| `DATASET_FUNCTIONAL_EVAL_PASS` | PARTIAL | Functional config Eval 7/7 passes; historical 987-request dataset report was not rerun and privacy human review is pending. |
| `FIXED_RESOURCE_CAPACITY_VERIFIED` | PARTIAL | 12/36 cells; 8-concurrency correctness stop; 32/64 unrun. |
| `PERFORMANCE_IMPROVEMENT_VERIFIED` | FALSE | No measured optimization or fair A/B. |
| `DATABASE_INVARIANTS_PASS` | PARTIAL | Final state after recovery is terminal with no duplicate receipt, but load-time expired reservations triggered stop and required reconciliation. |
| `SSE_FAILURE_MATRIX_VERIFIED` | PARTIAL | Two real Uvicorn SSE E2E tests and targeted failure paths passed; not every requested disconnect/close/SIGTERM/settlement-failure combination was independently exercised over TCP. |
| `CI_HANG_ROOT_CAUSE_IDENTIFIED` | TRUE | Linux faulthandler identified psycopg commit + proxy thread blocking in `recv()`; exact Linux mechanism reproduced and fixed. |
| `REMOTE_CI_PASS` | BLOCKED | No new Actions run for the modified commit yet. |
| `EVIDENCE_ARTIFACT_VERIFIED` | BLOCKED | No new remote artifact exists yet. |
| `CURRENT_SOURCE_IMAGE_ACCEPTED` | PARTIAL | Image build and local readiness/security properties verified; 4 High findings and SBOM caveat remain. |
| `DEPENDENCY_AUDIT_PASS` | TRUE | pip-audit exit 0, no known dependency vulnerabilities; editable project skipped. |
| `RESUME_IMPACT_DELIVERED` | TRUE | Role-specific evidence-bounded variants and interviewer Q&A are in report 14 and this report. |
| `RELEASE_READY` | FALSE | Capacity, remote CI/evidence, image findings and release gates are incomplete. |

## J. Stop and handoff

Do not restart the stopped matrix against the same database or infer 32/64 results. The safe next engineering action is a narrowly instrumented PostgreSQL concurrency experiment on a fresh isolated database that records SQLSTATE, `pg_stat_activity` wait events and lock waits; only after that should anyone alter lock granularity or timeouts. Separately, resolve the four High image findings and rerun the scan, complete human dataset privacy review, push the verified commits normally, and inspect the exact new Actions run and artifact.

`OVERNIGHT_SPRINT_COMPLETED = FALSE`
`RESUME_EVIDENCE_READY = TRUE`
`RELEASE_READY = FALSE`
