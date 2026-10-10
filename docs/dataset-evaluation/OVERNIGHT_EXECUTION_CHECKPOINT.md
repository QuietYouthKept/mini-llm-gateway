# Overnight Sprint Execution Checkpoint

Last updated: 2026-10-10T17:01Z (UTC)

## Identity and protection

- Workspace: `E:\mini-llm-gateway-dataset-eval`
- Branch / HEAD after verified source commit: `codex/dataset-evaluation` / `ffc179fe25f31b9f3a2475f5daf14e7ddf10bfe0`
- HEAD tree: `35f30af4dafce3bf9db78b8609a550117eeb60e7`
- Initial worktree state: 19 pre-existing uncommitted paths preserved; per-file SHA-256 and the tracked binary diff are in `E:\project-test-assets\01-gateway\results\overnight-sprint-20261010T155645Z\checkpoint\`.
- Prior raw datasets and evidence were not modified. Current scratch services use unique `overnight-sprint-20261010-*` names; no unrelated container was stopped.

## Completed so far

- Verified the recorded branch/HEAD and initial dirty-file hashes.
- Re-queried GitHub run `38043507409`: it was still `in_progress` on Full pytest after about six hours. Submitted cancellation; GitHub now reports `cancelled`. GitHub did not provide job logs for the cancelled in-progress job.
- Ran the real PostgreSQL reliability probe against a new isolated PostgreSQL 16 container: exit 0. The COMMIT-ACK-loss oracle passed; recovered receipt and idempotent replay left reservation `settled`, usage 12 tokens, one request audit, and one provider attempt.
- Reproduced the old Linux hang in the real commit-ACK-loss test. `faulthandler` identified the main thread blocked in psycopg `commit()` while the proxy's client-to-server thread remained in `recv()`. On Linux, closing the socket from another thread did not reliably interrupt the blocking receive.
- Patched the TCP proxy with socket/accept deadlines, `shutdown(SHUT_RDWR)` before close, bounded joins, and an explicit thread-stopped oracle. Added CI job timeout (45 minutes), pytest timeout (20 minutes), live `tee` output, `PIPESTATUS` exit capture, and `faulthandler_timeout=300`; locked CI sync now includes the `datasets` extra required by the preserved quality-audit test.
- Re-ran current dirty-worktree full tests in Linux/Python 3.11 with PostgreSQL/Redis: 214 passed in 49.91s; combined coverage 84.15%; independent coverage gate exit 0. Re-ran on Windows/Python 3.11: 214 passed in 22.77s; statements 86.79%, branch-only 71.28%, combined coverage 84.02%; `coverage report --fail-under=80` exit 0. These are local current-worktree results, not a new remote CI result.
- Final Windows gates all exited 0: Ruff, compileall, pytest, combined Coverage gate, Functional Eval (7/7), Security Eval (8/8), Provider Contract (13), Uvicorn TCP SSE E2E (2), tracked-file Secret Scan, and `git diff --check`. The first local wrapper attempt failed because of PowerShell argument expansion; it is retained separately and superseded by the corrected attempt-2 evidence.
- Redis adapter probe passed (20 concurrent global rate-limit checks: 10 admitted/10 rejected; shared cache; lease expiry/stale owner; explicit fail-open/fail-closed behavior). Two-Uvicorn-replica probe passed for cross-instance shared cache, distributed singleflight/lease, and a PostgreSQL budget race (one 200, one 429, one settled reservation, one provider attempt, two audits).
- Current-source image built successfully with immutable local image ID `sha256:c5712bf1ccb8871840c5ec6cad10c9e28b96e057bccced636380f3e17279ee34`; explicit PostgreSQL migration succeeded twice; repeated readiness was 200 after recovery; UID/GID 10001 and read-only rootfs verified; attempted write failed as expected; SIGTERM stop completed with exit 0 and no OOM.
- SBOM generated. Trivy 0.74.0 scan from that SBOM exited 0 and reported 26 findings (Critical 0, High 4, Medium 9, Low 13); it warned third-party SBOM scanning may be inaccurate. `pip-audit` exited 0 with no known dependency vulnerabilities (editable local project skipped).
- Capacity matrix stopped at 12/36 cells by its invariant stop rule. Concurrency 1 completed 9 cells at 100% success. Concurrency 8 completed two clean cells, then the third cell returned 0/1,984 HTTP successes (all `database_unavailable`/503). Snapshot showed 2 expired `reserved` rows; no further load was sent. Reconciliation released both and wrote two orphan-release records. Post-reconcile DB: 3,565 reservations (3,563 settled, 2 released, 0 reserved/uncertain), 3,565 finalization receipts, 0 duplicate request receipts, 4,132 audits, 3,563 attempts. This resolves terminal state but makes the capacity matrix partial; concurrency 32/64 were not run.
- No measured bottleneck optimization or fair A/B improvement was established. The database-unavailable cascade likely relates to serialized same-client reservation locks/timeouts, but failure-time SQLSTATE/wait-event evidence was not captured; this remains a hypothesis, not a confirmed root cause.
- Source fixes committed locally as `ffc179fe25f31b9f3a2475f5daf14e7ddf10bfe0` (`fix: bound postgres commit-ack probe and CI tests`). Only `.github/workflows/ci.yml`, `Dockerfile`, and `scripts/postgres_commit_ack_loss_probe.py` were staged. The original dataset harness, audit script/tests, reports 00-12, and other pre-existing work remain unstaged.

## Still blocked / incomplete

- The Linux clean-HEAD reproduction was interrupted at the PostgreSQL COMMIT-ACK test; the full successful Linux rerun used the current modified worktree in a disposable container. The historical GitHub run's exact logs remain unavailable because GitHub withheld them while in progress and exposed no logs after cancellation.
- Capacity concurrency 32 and 64, the remaining 24 matrix cells, and any optimized A/B comparison were not executed. The first database-unavailable invariant stop was respected.
- New remote CI has not yet run; no current commit's Actions result or Evidence Artifact exists yet. SSH 443 identifies `yqia0089-bot` and the remote branch is absent; GitHub CLI shows active `QuietYouthKept` with `repo`/`workflow` scopes. If pushing, use the existing GitHub CLI HTTPS credential path without altering shared SSH config; do not use the bot SSH identity.
- The PostgreSQL failure during the 8-concurrency cell is not root-caused. Current working hypothesis is an interaction between same-client advisory locking and short lock/statement timeout classification; SQLSTATE/wait events at the failure instant were not captured.
- Current image has 4 High Trivy findings and a third-party-SBOM accuracy caveat. It is built and smoke-tested, not accepted as release-ready.

## Next safe actions

1. Finish the three requested reports from the evidence already captured; do not restart the stopped matrix or claim a performance gain.
2. Review the exact staging list and generated docs for secrets/private samples; keep the original 19 pre-existing worktree paths untouched and unstaged unless individually reviewed.
3. Commit only verified CI/proxy/container fixes and new final reports with explicit paths; push normally only after confirming remote branch state and identity.
4. Verify the resulting GitHub Actions run and its Evidence Artifact; if unavailable or failing, report BLOCKED/FAILED rather than claiming remote acceptance.

## Checkpoint policy

Append new results below with UTC time, exact command, exit code and evidence paths. Do not overwrite or relabel prior experiment identities. If any correctness invariant fails, stop further load against that database and record the failure before recovery.
