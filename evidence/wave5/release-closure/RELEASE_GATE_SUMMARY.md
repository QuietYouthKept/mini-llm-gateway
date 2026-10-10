# Wave 5.1 Release Gate Summary

Final decision: `RELEASE_CANDIDATE_NOT_ACCEPTED`.

**PASS:** two exact clean OCI builds; Ruff; compileall; full local pytest (204 passed, 1 skipped); 81.08% branch coverage with an independent 80% gate; Security Eval 8/8; Provider Contract 13 passed; real TCP SSE 2 passed; PostgreSQL integration probe exit 0; Redis adapter probe exit 0; candidate non-root/read-only/capability restrictions observed; local Compose SSE request settled to one receipt and one audit; graceful SIGTERM and same-version restart recovered readiness.

**PARTIAL:** original PyPI EOF was not reproduced, so the proxy route is currently healthy but historical cause is unknown; PostgreSQL “commit unknown” used a synthetic acknowledgement loss after the real commit, not a TCP disconnect at COMMIT; metrics endpoint returned data but was not scraped/queried by Prometheus; current candidate runtime readiness passed after health checks.

**FAILED / BLOCKED:** Trivy reports 3 Critical and 88 High with no human risk approval; actual two-version rollback and schema-compatibility proof not performed; network DNS rebinding/redirect/egress policy not exercised; no end-to-end OTLP trace backend query; no controlled three-round performance matrix. These failures prevent release acceptance regardless of local unit/integration PASS.

Current source SHA is `c4ba57dafd380ca1d1a6ba39b40de0732d30a697`. No formal completion tag was created. Remote CI and Evidence Artifact have not been generated for this Wave 5.1 branch in this turn.
