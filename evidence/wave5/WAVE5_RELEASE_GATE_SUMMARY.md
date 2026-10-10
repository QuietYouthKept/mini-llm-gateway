# Wave 5 Release Gate Summary (interim)

This is an interim evidence-based status for the working tree based on remote baseline `3f57ce5d8cabbea148cc74c5023c2e5277ebd005`. The implementation and evidence are not yet committed or pushed. No Wave 5 completion tag is authorized.

| Gate | Status | Evidence / limitation |
|---|---|---|
| G01 Code quality | PASS | Final Ruff and compileall exit 0; full pytest 204 passed, 1 skipped; pytest-only branch coverage 81.08%; independent `coverage report --fail-under=80` exit 0. Locked dev+production Python dependency audit: no known vulnerabilities, exit 0. Logs under `final-gates/`. |
| G02 Real integration | PASS (scope tested) | PostgreSQL integration exit 0 including repeated migration, concurrent reservations, atomic finalization, idempotent replay, audit rollback, orphan reconciliation; Redis adapter and two-replica probes exit 0. |
| G03 PostgreSQL outage | PASS (defined matrix) | Isolated project-scoped Compose network; SIGKILL; 20/50 concurrency ×3; all chat requests 503, `/ready` <0.8 s 503, `/live` <0.032 s 200; maximum client chat 2.56 s. Raw JSON and summary retained. |
| G04 Consistency | PARTIAL | The outage path before durable reservation has zero audit/reservation rows and recovers after PG restart. Commit unknown, hard kill during settlement, and all reconciliation interleavings are not yet proven. |
| G05 Container integrity | PARTIAL | Default CMD, non-root, read-only rootfs, cap-drop, tmpfs, health and SIGTERM verified. Full clean committed-context build/provenance and resource limits are incomplete. |
| G06 Vulnerability security | BLOCKED | Locked Python dev+production dependency audit found no known vulnerabilities. Image SBOM generated, but current Docker Scout CVE and recommendations commands exited 1 because the scanner requested authentication. Current OS/base-image CVE status is unknown. |
| G07 Reproducibility | FAILED | First build completed; independent no-cache second build failed fetching locked uv from PyPI with TLS `UNEXPECTED_EOF_WHILE_READING`; no digest comparison possible. |
| G08 Upgrade/rollback | NOT EXECUTED | Startup, smoke, and SIGTERM restart were tested; no two-commit schema-compatible upgrade and healthy rollback drill was completed. Historical rc1 readiness 503 remains a known risk. |
| G09 Observability | PARTIAL | HTTP latency, event-loop lag/task, bounded lane and circuit metrics were sampled during outages. No full OTel collector/export/query, DB commit/lock wait, CPU/RSS, or telemetry sentinel pipeline verification. |
| G10 Network security | NOT EXECUTED | Configuration checks are not runtime DNS-rebinding, redirect, or container egress evidence. |
| G11 Performance | PARTIAL | Repeated bounded failure matrix only. No full 1/8/32/64 workload suite or fair Wave 4 comparison. |
| G12 GitHub delivery | NOT EXECUTED | No Wave 5 commit, push, remote CI, or artifact has been created in this run. |
| G13 Documentation | PARTIAL | Root cause, isolation, recovery, build and gate reports created; architecture/runbook, security, observability and interview deliverables remain incomplete. |

## Current decision

`RELEASE_CANDIDATE_NOT_ACCEPTED` — required security scan is blocked, reproducibility failed, and multiple acceptance gates remain unexecuted or partial. Passing development tests do not override these release gates.
