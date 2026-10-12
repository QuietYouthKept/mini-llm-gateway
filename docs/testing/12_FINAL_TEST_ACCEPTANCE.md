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
| Remote GitHub Actions | PASS | Run [38201945812](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38201945812), exact HEAD `95574cd11d59f851e92baff2562a82263f32721e`; all 25 workflow steps succeeded |
| Documentation closeout CI | PASS | Documentation-only commit `6d5e178455c37ffe287fd5dc7551357cee5aa6e3` also passed in [Run 38202404356](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38202404356); 247 passed, 1 skipped, PostgreSQL/Redis/HTTP-SSE/Provider Contract and all evidence steps passed |
| Remote pytest and coverage | PASS (coverage gate) | 247 passed, 1 skipped; coverage total 84.46%, line 87.02%, branch-rate submetric 72.94%; gate passed at configured 80% combined threshold |
| Remote PostgreSQL probe | PASS (bounded) | Cold reservation, shared-budget race, idempotent finalization, audit rollback, orphan reclaim, migrations twice and commit-ack-loss receipt recovery all reported successful; PG package combined coverage 62% (connection 60%, repository 64%) |
| Remote Redis probes | PASS (bounded) | Adapter + two-replica HTTP results passed: global rate limit 10 admitted/10 rejected, shared cache, fail-open/fail-closed classification, singleflight and lease expiry; Redis adapter combined coverage 88% |
| Remote HTTP/SSE and Provider Contract | PASS | HTTP/SSE 2 passed; Provider Contract 22 passed |
| Remote Evidence Artifact | PASS | Implementation artifact 11725997608 (160 files, manifest SHA-256 `61046c3217d67b716f081fc4ac68e558ae192712b2d3b464936ff72cf06b7d7b`) and docs-closeout artifact 11725893674 (160 files, manifest SHA-256 `5cda387136c96c7f7f3ec8e2462af0a94af5e1b0258dc0ddaa59ac18ca0c523e`); both downloaded ZIPs independently validated with 160/160, zero missing/extra/mismatched files |
| Remote validation Artifact | PASS | Implementation validation 11725997613 and docs-closeout validation 11725724020; both embedded validations say `passed: true` for matching SHA and 160 files |
| Hypothesis API/persistence probe | PASS | 15 generated HTTP examples: 8 valid/200, 2 bool/422, 5 long/400; all eight success persistence assertions passed |
| Schemathesis API contract | PASS | 127 generated cases, 127 passed on two Chat operations |
| Ruff | PASS | Final source check exit 0 (see external `reports/ruff.log`, `fault-provider/ruff-final.log`, `dataset/ruff-final.log`; targeted post-edits checks also archived) |
| compileall | PASS | Final exit 0, `reports/compileall-final.log` and `.exitcode` |
| Functional Eval | PASS | Final 7/7, exit 0, `reports/functional-eval-final.*` |
| Security Eval | PASS | Final 8/8, exit 0, `reports/security-eval-final.*` |
| Secret scan | PASS | Tracked source scan exit 0; final exact source/test/docs list was included by staging named files only |
| git diff --check | PASS | Final diff check exit 0, retained under `reports/` |
| Local PostgreSQL integration | BLOCKED_RESOURCE | Not configured in the Windows worktree; use bounded remote CI probe evidence above instead |
| Local Redis integration | BLOCKED_RESOURCE | Not configured in the Windows worktree; use bounded remote CI probe evidence above instead |
| Docker/build/scan/rollback | PARTIAL / historical failures | Current source not built/scanned; historical rootfs reproducibility FAILED, 44 High open, rc1 readiness rollback PARTIAL |
| Streaming performance/load/stress/soak | BLOCKED_RESOURCE | Host available memory below 6 GiB task floor; not run. |
| Remote CI branch coverage | PARTIAL | Both runs report 84.46% combined coverage (87.02% lines), while branch-rate submetric is 72.94%, below 80%. The configured combined coverage gate passed. Do not describe remote branch coverage as 80%+. |

## Overall disposition

`LOCAL_TEST_EVIDENCE_READY` is true for the bounded local tests above. Remote CI and evidence are also verified for the exact implementation commit. `RELEASE_READY` is false. PostgreSQL and Redis have bounded CI integration evidence, while full HA/failover, load, current-image security and deployment recovery gates remain unresolved. The local full suite's six skips include configured-service cases; remote CI used isolated PG/Redis services and passed its dedicated probes. The opt-in Toxiproxy case was run separately and passed.

## External raw evidence

See [`TEST_EVIDENCE_INDEX.md`](TEST_EVIDENCE_INDEX.md) for exact paths. Raw local logs, coverage database/XML, JUnit XML, failure iterations, SQLite test DBs, Toxiproxy result JSON, aggregate dataset output, and downloaded remote artifacts remain outside Git under the E: evidence root.
