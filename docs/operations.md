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
