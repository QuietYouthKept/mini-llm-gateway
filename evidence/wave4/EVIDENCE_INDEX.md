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
