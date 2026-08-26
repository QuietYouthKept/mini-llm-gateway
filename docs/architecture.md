# Architecture

mini-llm-gateway follows **Clean / Hexagonal Architecture**: the domain layer has
zero framework dependencies, and everything else adapts around it. The
composition root (`app/core/container.py`) wires concrete implementations into
one `AppContainer` that hangs off `app.state`.

## Layers

| Layer | Responsibility | Depends on |
| --- | --- | --- |
| `domain` | Models, ports, domain errors | nothing |
| `application` | Use cases & services (routing, fallback, budgets, guardrails) | domain |
| `infrastructure` | Providers, SQLite/PostgreSQL, Redis, config, metrics/tracing | domain (+ config models) |
| `interfaces/http` | Routes, schemas, auth, middleware, error handlers | application + domain |
| `core` | Settings, logging, startup, container (composition root) | everything |

The dependency rule: outer layers depend inward; the domain never imports a
framework or an adapter.

## Request lifecycle

For every `/v1/chat` (or `/v1/chat/completions`) request the `ChatService`
orchestrates this pipeline:

```
request
  -> request_id (middleware, contextvar)
  -> auth (API key -> client)
  -> streaming policy
  -> rate limit (sliding window)
  -> profile resolve
  -> input guardrail (aggregate request, then individual messages)
  -> input guardrail + exact cache lookup
  -> local + Redis singleflight (when configured)
  -> token estimate + atomic budget reservation lease
  -> routing (priority candidates)
  -> fallback (retry + circuit breaker per provider)
  -> output guardrail
  -> budget settle (or release on every failure/cancellation path)
  -> audit log (request_logs + provider_attempts)
  -> metrics
  -> response
```

## Provider abstraction

Every provider — mock or real — implements `ProviderPort` (`async chat(...)`).
`build_provider_registry` maps config `type` to a concrete adapter:

- `mock_fast` / `mock_stable` / `mock_slow` / `mock_error` — fault-injection mocks
- `fake_static` — always-succeeds last resort
- `openai_compatible` — real HTTP adapter for any OpenAI-style endpoint

Providers raise domain errors (`ProviderTimeoutError`,
`ProviderFailedError`, `ProviderBadStatusError`), which the fallback engine
maps to retry / circuit-breaker / fallback decisions. This is what lets a mock
and a real provider be treated identically by the rest of the gateway.

## Explainability

Every request produces a decision_trace (persisted in request_logs and returned
by /v1/chat): profile resolution, rate/budget/guardrail outcomes, cache hit or
miss, and per-provider selected/skipped/retried/failed decisions with reasons.
This makes the gateway's routing auditable rather than a black box, and powers
the failure-replay tool (scripts/replay_request.py) which re-runs historical
requests against the current config to detect regressions.

Tracing uses a bounded, prompt-free recorder with three stable span names:
`gateway.request`, `routing.resolve`, and `provider.attempt`. It is an adapter
seam for OpenTelemetry and can export OTLP/HTTP; prompt and response bodies are
never span attributes.

## State ownership

| Component | Local adapter | Shared adapter | Ownership consequence |
| --- | --- | --- | --- |
| budget + audit | SQLite | PostgreSQL | `RESERVED -> SETTLED|RELEASED`; expired leases need explicit reconciliation |
| rate limiter | memory | Redis | local limits are per-process; Redis limits are global |
| exact cache | memory | Redis | governed values shared; Redis lease coalesces cold misses globally |
| circuit breaker | memory | — | intentionally provider/process scoped |
| metrics | process registry | scrape/aggregate externally | counters are per-process |
| traces | bounded memory | OTLP exporter | export is optional and body-free |

Hot reload swaps the container snapshot atomically. Compatible state is reused;
incompatible retired containers remain alive for in-flight requests and are
closed once at application shutdown.

## Key decisions

- [ADR-0001: Clean Architecture](adr/0001-clean-architecture.md)
- [ADR-0002: ProviderPort abstraction](adr/0002-provider-port.md)
- [ADR-0003: SQLite + in-memory first](adr/0003-local-first-storage.md)
- [ADR-0004: Exact prompt cache first](adr/0004-exact-prompt-cache.md)
