# Migration to v1.0.0-rc1

SQLite startup upgrades the budget-reservation table in place. Existing active
rows receive a short lease and should be allowed to complete or reconciled with
`TokenBudgetService.reconcile_expired_reservations()` after deployment.

PostgreSQL deployments must run `migrations/postgresql/003_reservation_leases.sql`
through the existing startup migrator before rolling replicas. It adds durable
reservation state and expiry columns plus the new lease-aware admission
function. The application never scans reservations on the request path; run the
explicit reconciliation hook from a controlled maintenance job.

For Redis cache deployments, use a Redis-compatible server with Lua support.
The gateway now uses RESP2 deliberately. Rate-limit outage behavior is closed
by default; document and review any use of `GW_REDIS_RATE_LIMIT_FAILURE_MODE=open`.
