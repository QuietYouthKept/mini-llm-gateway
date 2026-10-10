# Wave 5 Execution Checkpoint

- Date: 2026-10-10 Asia/Shanghai
- Branch: `codex/wave5-release-hardening`
- Base/initial HEAD: `3f57ce5d8cabbea148cc74c5023c2e5277ebd005`
- Current source edits are uncommitted; current Git tree is dirty.
- Remote branch delivery: not yet attempted in this continuation; no Wave 5 CI Run or artifact exists.
- Release decision: `RELEASE_CANDIDATE_NOT_ACCEPTED`.

## Completed in this continuation

- Preserved the original dirty checkout and evidence outside the source worktree.
- Confirmed CI already has the independent 80% pytest-only coverage gate; no duplicate implementation added.
- Added bounded PostgreSQL DNS address caching/refresh, per-dependency blocking lanes and dedicated readiness lanes (in working tree).
- Fixed network error classification and singleflight release after database-unavailable; added a regression test. The new test failed before the fix and passed afterward.
- Removed the hard-coded shared Compose network so each project is isolated by its Compose project name.
- Fixed the Docker image CMD to invoke `python -m uvicorn` and removed the Compose command override.
- Ran isolated SIGKILL PG 20/50 ×3 matrix. Its oracle passed; pre-isolation matrices are retained but invalidated due shared network contamination.
- Ran PostgreSQL integration, Redis adapter and Redis two-replica probes.
- Verified staging default CMD, non-root/read-only runtime, health, synthetic Chat/SSE, and graceful SIGTERM.
- Captured a successful SBOM; current CVE/Recommendations scan was blocked by Docker Scout auth requirement.
- One no-cache rebuild failed at PyPI TLS transport; strict build reproducibility is not established.

## Latest quality gate

- Ruff: exit 0.
- compileall: exit 0.
- Final full pytest: 204 passed, 1 skipped, 81.08% branch coverage, exit 0.
- Independent coverage gate: exit 0 at 81.08%.
- Functional Eval: 7/7, exit 0.
- Security Eval: 8/8, exit 0.
- Provider Contract: 13 passed, exit 0.
- TCP SSE: 2 passed, exit 0.
- Secret Scan: exit 0.
- Locked dev+production pip-audit: exit 0, no known vulnerabilities.
- PostgreSQL Integration: exit 0; dedicated repository coverage 59%.
- Redis adapter: exit 0; Redis two-replica: exit 0.
- PostgreSQL outage matrix: exit 0 for valid isolated matrix.
- `git diff --check`: exit 0.

## Next safe commands

1. Recheck SSH identity and remote state, then normal-push the committed Wave 5 branch.
2. Verify the remote CI Run, failure details, coverage, and uploaded artifact if push succeeds.
3. Do not create a completion tag while G06/G07 or other mandatory gates remain blocked/failed.
