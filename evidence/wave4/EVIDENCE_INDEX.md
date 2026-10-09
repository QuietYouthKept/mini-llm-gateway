# Wave 4 Evidence Index

Evidence is local synthetic unless explicitly stated. SHA-256 is in sibling machine-readable outputs or can be regenerated with `Get-FileHash -Algorithm SHA256`. Commit `d8d8d2d` contains A3 validator changes only; B application/test changes were uncommitted at report generation. No GitHub Wave 4 run or artifact exists.

| Claim | Commit / state | Test or command | Raw evidence | Result and limitation |
|---|---|---|---|---|
| Worktree preserved | Pre-Wave4 snapshot | `git bundle verify` and source hash inventory | External `_wave4-preservation/20261009-203831-0073fd39` | PASS; bundle SHA `FA751D22B3D8F8DBAFF77760F72725BC32A381A6A0CF0AC29284C5C1CAEA41D5` |
| ZIP evidence validator | `d8d8d2d` | `pytest tests/unit/test_evidence_artifact_validator.py` (focused run) | CI workflow/scripts/tests in commit | PASS locally; remote artifact validation pending |
| Static checks | Local worktree | Ruff; compileall; `git diff --check` | `ruff-final.log`, `compileall-final.log`, `diff-check-final.log` and exit codes | PASS |
| Full pytest | Local worktree | pytest with JUnit and branch coverage | `pytest-final-junit.xml`, `pytest-final.log`, `pytest-final-coverage.xml` | 193 passed; 79.92%, below required 80%; gate FAILED |
| Integration-inclusive coverage | Local worktree | Merge pytest + PG + Redis + replica coverage | `combined-coverage-final.log`, `.coverage-combined` | 85.72%; supplementary only, not pytest-only gate |
| Eval/provider/SSE/security gates | Local worktree | Functional 7/7; Security 8/8; TCP SSE; Provider Contract | `functional-eval-final.log`, `security-eval-final.log`, `tcp-sse-final.log`, `provider-contract-final.log` | PASS for tested cases |
| Secret/dependency checks | Local worktree | `secret_scan.py`; `pip-audit --skip-editable --format=json` | `secret-scan-final.log`, `dependency-audit-final.log` | PASS; no known Python vulnerabilities reported; not an image scan |
| PostgreSQL repository | Local worktree | `scripts.postgres_integration_probe` | `postgres-integration-covered.json`, `.exitcode` | PASS for enumerated probe cases |
| Redis adapters | Local worktree | `scripts.redis_adapter_integration_probe` | `redis-adapter-covered.json`, `.exitcode` | PASS for enumerated probe cases |
| Two replicas | Local worktree | `scripts.redis_two_replica_integration_probe` | `redis-two-replica-covered.json`, `.exitcode` | PASS for tested shared Redis/PG behavior |
| PG outage | Local staging | 20 concurrent TCP requests while PostgreSQL stopped | `staging-acceptance-final.json` | FAILED: max 9.594s, readiness unavailable by ~3.172s, liveness 1.547s |
| Container hardening/staging | Local dirty image | identity, rootfs, migrations, SSE, SIGTERM | `staging-acceptance-final.json` | Partial; outage readiness and rc1 rollback failed |
| CVE/SBOM | Local dirty image | Docker Scout SBOM and CVE scan | `image-sbom.cdx.json`, `image-cves.exitcode` | SBOM 177 packages; current CVE scan blocked by Docker auth |
| Synthetic performance | Local staging | `scripts/load_test.py`; 10 requests per concurrency | `benchmark-corrected-concurrency-*.json` | Exploratory only; 40/40 returned 200, single tiny run |
| PG backup/restore | Isolated DB container | `pg_dump`/`pg_restore`, row count compare, write smoke | `pg-backup-restore-result.json` | PASS; hash/counts recorded; 2.114s synthetic local run |
| GitHub delivery | No authorized SSH writer | SSH 443 identity check | Prior identity-check transcript | BLOCKED; no Wave4 push, CI run or artifact |

## Wave 4.1 Delivery Update — 2026-10-10

The table above is the historical snapshot from report generation. This addendum supersedes its GitHub-delivery and coverage-gate status without rewriting that history.

| Claim | Commit / run | Raw evidence | Result |
|---|---|---|---|
| CI coverage gate | `69bd8d89aea7a365c4199e6179a36c5e48f8baad`, [run 37955506857](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/37955506857) | `remote-run-37955506857/gateway-ci-evidence-69bd8d89aea7a365c4199e6179a36c5e48f8baad-run-37955506857/pytest.log`, `coverage-gate.log`, and `status/*.exitcode` | PASS: 199 tests, pytest exit 0, independent `coverage report --fail-under=80 --precision=2` exit 0, pytest-only branch coverage 84.04%. The negative below-threshold gate regression is included in the suite. |
| Uploaded evidence | Artifact IDs `11628440260` and `11628380375` | `remote-run-37955506857/gateway-evidence-validation-69bd8d89aea7a365c4199e6179a36c5e48f8baad-run-37955506857/artifact-validation.json` | PASS: manifest SHA `4d8755df06742243093f38018acdcdb89fa0553e4f758295cdbdf56d5f100357`, 155 expected/actual files, no missing/extra/hash mismatches; validated archive uses neutral `gateway-evidence-11628440260.zip` name. |
| Provider/eval/security/hygiene gates | Same run | Evidence artifact `functional-eval.txt`, `security-eval.txt`, `secret-scan.txt`, `ruff.log`, `compileall.log`, and `diff-check.log` | PASS: Functional 7/7; Security 8/8; secret scan, Ruff, compileall, and diff check passed. PostgreSQL/Redis integration, two-replica probes, HTTP/SSE, Provider Contract, and dependency audit jobs also passed. |
| PostgreSQL outage under TCP load | Local isolated Compose, safe-audit build | `wave41-postgres-safe-audit-20.json`, `wave41-postgres-safe-audit-50.json` | FAILED release gate: all completed requests were classified as 503 (one of 20 had no HTTP status); audit/reservation rows remained zero, but `/ready` timed out at 4.172s/4.187s, `/live` took 1.641s/3.891s, and slowest request took 13.593s/14.094s. Thread queue / cancellation / connection-wait behavior remains unresolved. |
| Container/Staging acceptance | Preserved local staging evidence | `staging-acceptance-final.json`, `WAVE4_CONTAINER_REPORT.md`, `image-cves.exitcode` | PARTIAL/FAILED: normal hardened container, repeated migration, SSE settlement, and SIGTERM smoke passed; concurrent PG outage and rc1 rollback readiness failed. Current-image scan was blocked by Docker authentication; historical 44 High applies to an older image, not the current image. Strict rootfs reproducibility remains failed. |
