# Operations contract

## Example SLIs and SLOs

These are recommended operational targets, not workstation measurements:

| SLI | Example target |
| --- | --- |
| Gateway availability | 99.9% successful non-policy requests per 30 days |
| Gateway overhead latency | Establish a p95 target after deployment baseline |
| Provider-attempt error rate | Alert when sustained above normal provider baseline |
| Audit persistence | 99.99% successful audit writes |
| Fallback, budget, rate-limit, cache | Track as decision-quality and capacity signals, not availability alone |

`deploy/prometheus/alerts.yml` provides example expressions. Metric registries
are process-local, so Prometheus must scrape every replica and aggregate before
alerting. The budget-leak alert is enabled by emitting a reconciliation result
from the maintenance job; it is intentionally not inferred from a request-path
scan.

Import `deploy/grafana/mini-llm-gateway-dashboard.json` into Grafana and select
the Prometheus data source. It demonstrates the SLO signals above alongside
provider latency, phase-level gateway latency, retry amplification, cache hit
ratio, and budget lease recovery. The included alert rules cover the three
operator drills: sustained provider failure/timeout, budget or audit storage
failure, and Redis-dependent operation failure.

## State and failure matrix

| State | Backend | Scope | Failure behavior |
| --- | --- | --- | --- |
| Rate limit | Redis / memory | global / process | Redis default fail-closed (503); memory is process-local |
| Cache | Redis / memory | shared / process | fail-open miss when Redis fails |
| Singleflight | Redis lease / memory | global / process | owner-safe TTL recovery; degrade to local on Redis loss |
| Circuit | memory | process/provider | intentionally non-global |
| Budget | PostgreSQL / SQLite | database shared | durable reservation lease; explicit reconciliation after crash |
| Audit | PostgreSQL / SQLite | database shared | request/attempt insert is transactional; error is surfaced |

TLS termination belongs at the ingress boundary. See
`deploy/nginx/nginx.conf.example`; it is a topology illustration, not a
production certificate configuration.

## Wave 5.1 release acceptance status

The local candidate has repeatable clean OCI builds, and isolated PostgreSQL,
Redis, and TCP SSE probes have passed. The image is nevertheless **not
accepted for release**: Trivy found unresolved Critical/High issues. The
PostgreSQL acknowledgement-loss probe is synthetic after commit, not a dropped
wire acknowledgement; a two-version rollback and OTLP/Prometheus query drill
were not performed. Do not use the same-version SIGTERM restart as rollback
evidence. The detailed gate report is
[`evidence/wave5/release-closure/RELEASE_GATE_SUMMARY.md`](../evidence/wave5/release-closure/RELEASE_GATE_SUMMARY.md).

Until blockers are closed, keep this candidate in disposable local staging
only. A deployment must retain PostgreSQL state during rollback, verify schema
compatibility before changing binaries, and use forward recovery if the prior
binary cannot read the migrated schema.
