# Routing, fallback, retry and breaker report

## Executed evidence

The full pytest suite and focused reliability subset exercised the existing deterministic unit/SQLite assertions for pre-token fallback, no fallback after output, circuit-open behavior, missing provider behavior, retry/fallback semantics, and attempt/audit state. The focused command covered `test_fallback_service.py`, `test_circuit_breaker.py`, `test_streaming_failure_semantics.py`, `test_token_budget_service.py`, and `test_uvicorn_streaming_e2e.py`: 52 passed.

The new real-TCP post-token reset test additionally proved that after three client-visible chunks Provider B was not called, even though fallback was configured for `provider_failed`. This verifies the post-output no-transparent-fallback contract for one injected reset scenario.

## Not established

This round did not run a dedicated exhaustive matrix across provider 429/`Retry-After`, all retry budgets, circuit state transitions under concurrency, or multi-provider routing against PostgreSQL. The synthetic fault server has deterministic response modes, but a mode's existence is not a passing test. No retry-rate or failover-latency claim is made.
