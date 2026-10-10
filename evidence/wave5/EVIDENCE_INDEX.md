# Wave 5 Evidence Index

All measurements in this directory were generated in the disposable Wave 5 worktree unless explicitly marked as a historical baseline. Evidence from the primary dirty checkout was preserved outside this worktree and was not overwritten.

## Release and reliability summaries

- `PG_ROOT_CAUSE_ANALYSIS.md` — DNS resolver, same-key singleflight, and Docker network contamination findings.
- `PG_ISOLATION_DESIGN.md` — implemented fault isolation and what remains unproven.
- `PG_RECOVERY_REPORT.md` — isolated SIGKILL and PostgreSQL recovery results.
- `CONTAINER_REPRODUCIBILITY_REPORT.md` — actual runtime validation, failed no-cache rebuild, and scanner block.
- `WAVE5_RELEASE_GATE_SUMMARY.md` — per-gate interim status; release candidate not accepted.
- `EXECUTION_CHECKPOINT.md` — resumable task state and next safe steps.

## PostgreSQL raw matrices

- `pg-outage-p1-isolated-repeat3.json` and `pg-outage-p1-isolated-summary.csv/.json` — valid 20/50 concurrency ×3 SIGKILL matrix on a project-scoped network; oracle passed.
- `pg-outage-reused-client-repeat3.json`, `pg-outage-p1-fix-repeat3.json`, `pg-outage-repeat3.json`, `pg-outage-sigkill-repeat3.json`, and `pg-outage-cache-repeat3.json` — preserved earlier runs. The first two shared an explicitly named network and could reach another project's PostgreSQL; they are invalid for acceptance. Earlier runs without the final isolated topology are diagnostic only.

## Final gate outputs

`final-gates/` contains command outputs, pytest JUnit XML, pytest-only Coverage XML/HTML and data, PostgreSQL/Redis probe outputs, dependency audit, Scout/SBOM outputs, Docker build logs, and runtime staging evidence. The final full pytest result is 204 passed, 1 skipped, 81.08% branch coverage; independent 80% coverage gate exit 0. Raw logs retain command-specific exit status in the execution transcript; Wave 5 GitHub Actions evidence has not yet been generated.

The latest Wave 5 GitHub Actions run for source commit `294d631acc022c0a121227f078115d1416850288` is [Run 38010145778](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38010145778). CI Evidence Artifact ID `11652133695`; validation Artifact ID `11652323443`. Both were downloaded. Its Manifest binds the tested SHA/tree and 155 evidence files; 155/155 local file hashes matched, with zero missing/extra files and no mismatches. The manifest SHA-256 is `b7a3dc11bfb0212d7cea2f2ec6b8e4265e11bfb385c7ebfa25234a04ab9eb68c`.

Remote pytest: 205 passed, 84.02% branch coverage; separate coverage gate exit 0. The Docker Scout CVE/Recommendations output files contain the actual authentication error and are not scan results. The no-cache and clean Git-archive build logs record PyPI TLS handshake EOF. See the reproducibility report for decision and scope.
