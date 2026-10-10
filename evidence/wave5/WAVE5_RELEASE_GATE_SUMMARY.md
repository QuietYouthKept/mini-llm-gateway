# Wave 5 Release Gate Summary

Latest tested code commit: `294d631acc022c0a121227f078115d1416850288` (tree `a99fa6a56f6e2e06bbf56ca863ddbacc9b2f2739`), based on remote baseline `3f57ce5d8cabbea148cc74c5023c2e5277ebd005`. Four scoped commits were pushed normally to `codex/wave5-release-hardening`. No Wave 5 completion tag is authorized.

| Gate | Status | Evidence / limitation |
|---|---|---|
| G01 Code quality | PASS | Local final before the Dockerfile-only follow-up: Ruff/compileall exit 0, pytest 204 passed/1 skipped, pytest-only branch coverage 81.08%, independent coverage gate exit 0. Latest remote CI for SHA `294d631`: pytest 205 passed, branch coverage 84.02%, pytest and independent 80% gate exit 0; all CI steps passed. |
| G02 Real integration | PASS (scope tested) | PostgreSQL integration exit 0 including repeated migration, concurrent reservations, atomic finalization, idempotent replay, audit rollback, orphan reconciliation; Redis adapter and two-replica probes exit 0. |
| G03 PostgreSQL outage | PASS (defined matrix) | Isolated project-scoped Compose network; SIGKILL; 20/50 concurrency ×3; all chat requests 503, `/ready` <0.8 s 503, `/live` <0.032 s 200; maximum client chat 2.56 s. Raw JSON and summary retained. |
| G04 Consistency | PARTIAL | The outage path before durable reservation has zero audit/reservation rows and recovers after PG restart. Commit unknown, hard kill during settlement, and all reconciliation interleavings are not yet proven. |
| G05 Container integrity | PARTIAL | Default CMD, non-root, read-only rootfs, cap-drop, tmpfs, health and SIGTERM verified on the earlier local image. The final Dockerfile avoids packaging source, but the exact latest commit could not be built locally due PyPI TLS EOF; clean committed-image runtime and provenance therefore remain incomplete. |
| G06 Vulnerability security | BLOCKED | Locked Python dev+production dependency audit found no known vulnerabilities. Image SBOM generated, but current Docker Scout CVE and recommendations commands exited 1 because the scanner requested authentication. Current OS/base-image CVE status is unknown. |
| G07 Reproducibility | FAILED | A cached experimental build completed, but the no-cache build and two clean Git-archive builds failed downloading from PyPI with TLS handshake EOF. There are not two completed builds to compare; no rootfs/layer/config/manifest equality is claimed. |
| G08 Upgrade/rollback | NOT EXECUTED | Startup, smoke, and SIGTERM restart were tested; no two-commit schema-compatible upgrade and healthy rollback drill was completed. Historical rc1 readiness 503 remains a known risk. |
| G09 Observability | PARTIAL | HTTP latency, event-loop lag/task, bounded lane and circuit metrics were sampled during outages. No full OTel collector/export/query, DB commit/lock wait, CPU/RSS, or telemetry sentinel pipeline verification. |
| G10 Network security | NOT EXECUTED | Configuration checks are not runtime DNS-rebinding, redirect, or container egress evidence. |
| G11 Performance | PARTIAL | Repeated bounded failure matrix only. No full 1/8/32/64 workload suite or fair Wave 4 comparison. |
| G12 GitHub delivery | PASS | Latest Run [38010145778](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38010145778) tested SHA `294d631` and succeeded. Evidence Artifact `11652133695` (archive digest `sha256:1feee95b39b80d568c4cdbaf5b41fa977bc553f84200bed1cfbeaca1547af343`); validation Artifact `11652323443`. Downloaded and rehashed: 155 declared/155 actual files, zero mismatches; manifest SHA-256 matched `manifest.sha256`, value `b7a3dc11bfb0212d7cea2f2ec6b8e4265e11bfb385c7ebfa25234a04ab9eb68c`. |
| G13 Documentation | PARTIAL | Root cause, isolation, recovery, build and gate reports created; architecture/runbook, security, observability and interview deliverables remain incomplete. |

## Current decision

`RELEASE_CANDIDATE_NOT_ACCEPTED` — required security scan is blocked, reproducibility failed, and multiple acceptance gates remain unexecuted or partial. Passing development tests do not override these release gates.

The remote CI workflow produced non-blocking platform warnings: Actions currently run under Node.js 24 compatibility while the pinned checkout/setup/upload actions target Node.js 20, and `ubuntu-latest` is scheduled to migrate to Ubuntu 26. Review action versions and runner changes in a separate CI maintenance task.
