# Wave 5.1 Release Gate Summary

Final decision: `RELEASE_CANDIDATE_NOT_ACCEPTED`.

**PASS:** two exact clean OCI builds; Ruff; compileall; full local pytest (204 passed, 1 skipped); 81.08% branch coverage with an independent 80% gate; Security Eval 8/8; Provider Contract 13 passed; real TCP SSE 2 passed; PostgreSQL integration probe exit 0; Redis adapter probe exit 0; candidate non-root/read-only/capability restrictions observed; local Compose SSE request settled to one receipt and one audit; graceful SIGTERM and same-version restart recovered readiness.

**PARTIAL:** original PyPI EOF was not reproduced, so the proxy route is currently healthy but historical cause is unknown; PostgreSQL “commit unknown” used a synthetic acknowledgement loss after the real commit, not a TCP disconnect at COMMIT; metrics endpoint returned data but was not scraped/queried by Prometheus; current candidate runtime readiness passed after health checks.

**FAILED / BLOCKED:** Trivy reports 3 Critical and 88 High with no human risk approval; actual two-version rollback and schema-compatibility proof not performed; network DNS rebinding/redirect/egress policy not exercised; no end-to-end OTLP trace backend query; no controlled three-round performance matrix. These failures prevent release acceptance regardless of local unit/integration PASS.

The Wave 5.1 branch was pushed normally over SSH 443. GitHub CI run [38015606740](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38015606740), tested commit `de6d2a3e0d8a4a0b61afc75fbfe16d2c4beceda3`, completed successfully: 205 passed in 15.87 seconds, 84.02% branch coverage, independent 80% coverage gate passed, and the workflow's PostgreSQL, Redis, two-replica, SSE, Provider Contract, evaluation, secret, dependency and hygiene jobs passed. This is Development CI, not the complete release gate.

Evidence Artifact `11656405425` and validation Artifact `11656695290` were downloaded. Independent local verification found 155/155 files, no extra/missing files, no size/hash mismatch, and matching manifest SHA-256 `850ac4938b1594821c101e93ca817b6b293c1dbf56fabf2e56986a0004a37db8`. Full local copies and validation JSON are under `remote-artifacts/`. No formal completion tag was created; release decision remains NOT ACCEPTED.
