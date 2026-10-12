# Deployment, recovery and observability matrix

| Gate | Status | Evidence / limitation |
|---|---|---|
| Current source tests and local loopback scenarios | PASS | This wave's pytest, Hypothesis, Schemathesis and Toxiproxy evidence |
| PostgreSQL fault recovery / multi-instance consistency | BLOCKED_RESOURCE | No isolated PostgreSQL stack; integration skipped |
| Redis outage / multi-instance cache and rate limit | BLOCKED_RESOURCE | No isolated Redis stack; probes not run |
| Docker rootfs reproducible build | FAILED (historical, still open) | Wave5 report: two no-cache builds differed; 6/8 layers matched and image sizes differed |
| Historical image vulnerability scan | PARTIAL / open | 44 High, 0 Critical in the historical scan; the current source image was not rebuilt or rescanned |
| Readiness rollback | PARTIAL / failed criterion | Historical rc1 readiness returned 503 during recovery, then 200 after roughly 6 seconds; rollback not fully accepted |
| SIGTERM, read-only rootfs, migration replay in a fresh stack | NOT RUN this wave | Container resource gate blocked; no fresh Docker validation |
| Production alert delivery / on-call recovery | NOT VERIFIED | No receiver or production-like operational exercise |

These statuses preserve the historical test outcomes. This wave did not alter Docker or deployment configuration and does not change release readiness.
