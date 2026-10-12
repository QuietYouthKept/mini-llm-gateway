# Wave 6 final test acceptance

## Identity

- Base source commit: `16f3b527e0b9fe86560b9bc7aaf58031cd27e651`; base tree: `d6f102af676ad46960b2b68962c73318867862e1`.
- Worktree: `E:\mini-llm-gateway-fault-testing`; branch: `codex/gateway-fault-contract-benchmark`.
- Evidence root: `E:\project-test-assets\01-gateway\results\wave6-fault-contract-20261012T030137Z`.
- The worktree was based on the source commit above; its implementation and test changes were present during the completed runtime test runs. The base SHA identifies the parent revision, not the final implementation revision. Documentation-only refinements made after the full pytest run do not alter executable code.

## Gate results

| Gate | Result | Actual result / evidence |
|---|---|---|
| Full pytest, pytest-only coverage | PASS | 242 passed, 6 skipped; 81.37% branch coverage; `coverage report --fail-under=80` exit 0 |
| Focused reliability regression | PASS | 52 passed across fallback, breaker, stream failure, accounting and Uvicorn TCP tests |
| Toxiproxy post-token TCP reset | PASS | Final rerun 1 passed; three client chunks, `provider_failed`, no Provider B, one audit, settled reservation |
| Hypothesis API/persistence probe | PASS | 15 generated HTTP examples: 8 valid/200, 2 bool/422, 5 long/400; all eight success persistence assertions passed |
| Schemathesis API contract | PASS | 127 generated cases, 127 passed on two Chat operations |
| Ruff | PASS | Final source check exit 0 (see external `reports/ruff.log`, `fault-provider/ruff-final.log`, `dataset/ruff-final.log`; targeted post-edits checks also archived) |
| compileall | PASS | Final exit 0, `reports/compileall-final.log` and `.exitcode` |
| Functional Eval | PASS | Final 7/7, exit 0, `reports/functional-eval-final.*` |
| Security Eval | PASS | Final 8/8, exit 0, `reports/security-eval-final.*` |
| Secret scan | PASS | Tracked source scan exit 0; final exact source/test/docs list was included by staging named files only |
| git diff --check | PASS | Final diff check exit 0, retained under `reports/` |
| PostgreSQL integration | BLOCKED_RESOURCE | Not configured; integration cases skipped. No PG persistence claim. |
| Redis integration / multi-instance | BLOCKED_RESOURCE | Not configured; not run. |
| Docker/build/scan/rollback | PARTIAL / historical failures | Current source not built/scanned; historical rootfs reproducibility FAILED, 44 High open, rc1 readiness rollback PARTIAL |
| Streaming performance/load/stress/soak | BLOCKED_RESOURCE | Host available memory below 6 GiB task floor; not run. |
| Remote GitHub CI / evidence artifact | NOT RUN | No push or remote run performed in this execution yet. |

## Overall disposition

`LOCAL_TEST_EVIDENCE_READY` is true for the bounded tests above after the final tracked-source gate run and commit. `RELEASE_READY` is false. PostgreSQL, Redis, load, current-image security and deployment recovery gates remain unresolved. The full suite's six skips must be read from the JUnit report; five are PostgreSQL-dependent and the opt-in Toxiproxy test is skipped unless explicitly enabled (the latter was run separately and passed).

## External raw evidence

See [`TEST_EVIDENCE_INDEX.md`](TEST_EVIDENCE_INDEX.md) for exact paths. Raw logs, coverage database/XML, JUnit XML, failure iterations, SQLite test DBs, Toxiproxy result JSON, and aggregate dataset output remain outside Git under the E: evidence root.
