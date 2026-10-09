# Next Phase Plan

## P1 — release blockers

1. Complete PostgreSQL outage isolation: bounded per-dependency queue/pool, fast failure under concurrency, event-loop/worker/pool telemetry, 20–50 concurrent TCP outage tests and durable-state reconciliation after restart.
2. Raise pytest-only branch-aware coverage to the existing 80% threshold using meaningful tests; do not rely on integration-merged coverage to hide 79.92% pytest-only coverage.
3. Obtain an authorized QuietYouthKept SSH identity; push Wave 4 normally, run Linux CI, download its artifact and validate manifest/ZIP contents.
4. Run authenticated current-image SBOM/CVE scan; triage package-level High findings. Historical 44 High is not current-image evidence.
5. Qualify a rollback candidate for readiness. Existing rc1 returned 503 and is not an acceptable rollback target.
6. Resolve strict image reproducibility only with documented evidence and release authority; status currently failed.

## P2 — production qualification

7. Runtime DNS/redirect/egress control tests; current status `NETWORK_EGRESS_NOT_VERIFIED`.
8. Live OpenTelemetry Collector + Prometheus/Grafana validation, fault correlation, redaction tests and alert exercise.
9. Expand benchmarks with fixed CPU/memory limits, warmup, 3+ repetitions, 1/8/32/64 concurrency across workload classes and single/two replicas; capture TTFT, provider/gateway breakdown, resource and shared-state metrics.
10. Repeat backup/restore with documented policy and representative synthetic volume, integrity checks and measured restore/readiness; do not infer RPO without a backup schedule.

No unrelated RAG/vector/search work is in scope. No production deployment or production-provider spend is authorized by this plan.
