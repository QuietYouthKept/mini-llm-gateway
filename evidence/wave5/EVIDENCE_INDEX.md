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

The Docker Scout CVE/Recommendations output files contain the actual authentication error and are not scan results. The no-cache second build log records the PyPI TLS `UNEXPECTED_EOF_WHILE_READING` error. See the reproducibility report for decision and scope.
