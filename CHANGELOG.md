# Changelog

## [1.0.0-rc1] - 2026-08-26

### Added

- Redis owner-safe distributed singleflight and a live two-replica probe.
- Durable budget reservation states, expiry leases, and explicit reconciliation.
- Example Prometheus alerts, release checklist, TLS boundary example, and OSS docs.

### Changed

- Redis adapters use RESP2 for compatibility with Redis-compatible servers.
- Shared rate limiting is fail-closed by default when Redis is unavailable.

### Fixed

- A crashed process can no longer retain a budget reservation indefinitely.
- A Redis lease owner cannot delete a successor's lease.

### Known limitations

- Real paid providers, cloud-region HA, production certificates, and multi-day
  soak results are intentionally unverified.
