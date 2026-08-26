# ADR-0003: SQLite + in-memory rate limiting first

- Status: Accepted
- Date: 2026-08-14

## Context

The gateway needs persistent budget usage and request audit trails, plus a rate
limiter. A production gateway would use Postgres and Redis, but this project is
a local-first, runnable demonstration.

## Decision

- Use SQLite (WAL mode) for durable state: clients, token_budget_usage,
  request_logs, provider_attempts, config_events.
- Use an in-memory sliding-window rate limiter (**process-local**, not global).
- Hide both behind repository/service interfaces (TokenBudgetRepository,
  RequestLogRepository, RateLimiter) so the implementation can be swapped.

## Consequences

- Zero-infrastructure startup: clone, install, run.
- Rate limiting is not distributed across replicas — documented as a known
  limitation; the interface is the seam for a Redis token-bucket swap.
- Circuit breakers and prompt-cache singleflight are also process-local. A
  multi-replica deployment must not describe these controls as global.
- SQLite is fine for the write volume of a demo; the repository interfaces keep
  the Postgres migration mechanical, not architectural.
