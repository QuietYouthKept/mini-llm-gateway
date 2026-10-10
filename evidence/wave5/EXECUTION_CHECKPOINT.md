# Wave 5 Execution Checkpoint

- Date: 2026-10-10 Asia/Shanghai
- Branch: `codex/wave5-release-hardening`
- Base/initial HEAD: `3f57ce5d8cabbea148cc74c5023c2e5277ebd005`
- Source commits pushed: `896d4ff` (reliability), `13cf436` (container/staging), `5e74fdb` (evidence), `294d631` (avoid source wheel build in image).
- Remote branch HEAD: `294d631acc022c0a121227f078115d1416850288`; remote CI Run `38010145778` succeeded and its artifacts were downloaded and verified.
- Remaining local untracked files are preserved diagnostics/coverage outputs; they were not staged wholesale.
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
- Normal push succeeded using the existing QuietYouthKept-specific SSH identity (explicit identity selection); the default SSH identity was the bot account.
- CI evidence Artifact `11652678485`; Validation Artifact `11652294607`; 155/155 files and hashes verified.
- Latest CI evidence Artifact `11652133695`; Validation Artifact `11652323443`; 155/155 files and hashes verified; pytest 205 passed and 84.02% branch coverage.
- Clean Git-archive builds attempted for commits `5e74fdb` and `294d631`; both failed at PyPI TLS handshake EOF. No clean image from the latest SHA exists.

## Latest quality gate

- Ruff: exit 0.
- compileall: exit 0.
- Local final full pytest: 204 passed, 1 skipped, 81.08% branch coverage, exit 0.
- Remote CI pytest: 205 passed, 84.02% branch coverage; independent coverage gate exit 0.
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

1. Continue remaining Wave 5 gates from the currently clean committed HEAD; preserve remaining local raw diagnostics.
2. Resolve Docker Scout authentication through the user's normal Docker Desktop sign-in flow, then scan the exact clean-commit image. Do not provide credentials to Codex.
3. Retry the reproducibility build only after PyPI TLS/network connectivity is restored; compare two completed builds from a clean commit context.
4. Do not create a completion tag while G06/G07 or other mandatory gates remain blocked/failed.
