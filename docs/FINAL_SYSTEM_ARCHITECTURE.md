# mini-llm-gateway — Final System Architecture

Status snapshot: 2026-10-10, source commit `4febd225a1e5fc1144cda0f4596a5af16242c2a9`. This document describes the checked-in code, not a production deployment approval. The R10 lane-isolation change has CI and repository-integration evidence, but no final image has yet been built from this commit and the controlled load comparison is still running.

## Purpose and limits

The service is a policy and accounting gateway in front of configured LLM providers. It authenticates a client, applies rate and budget controls, selects/retries/falls back across providers, guards output, records request/attempt decisions, and exposes buffered Chat and SSE endpoints. It is a single-tenant reference deployment (`gateway.tenant_mode: single`), not a hosted multi-tenant control plane. The deterministic mock provider is for tests and capacity experiments; its results are not real-model capacity or billing evidence.

It does not provide provider-side exactly-once execution, global circuit-breaker state, a managed PostgreSQL/Redis HA or backup service, a validated production egress firewall, or proof of lost PostgreSQL COMMIT acknowledgement at the wire. Metrics and traces are emitted by application instances; a real backend must scrape/export and correlate them.

## Runtime composition

Uvicorn hosts a FastAPI application. `app/main.py` creates the application and lifespan; `app/core/container.py` is the composition root that selects SQLite or PostgreSQL persistence, memory or Redis rate/cache adapters, provider implementations, services, metrics, tracing, and the bounded synchronous-I/O bridge. Request IDs are established in HTTP middleware and passed to domain errors, audit records, and traces.

| Area | Current implementation |
| --- | --- |
| `app/domain` | Provider contracts, request/response models, ports, structured errors, routing decisions; framework-independent. |
| `app/application/services` | Chat orchestration, routing, fallback, budget, cache/singleflight, readiness, and bounded blocking I/O. |
| `app/infrastructure/providers` | Mock/fake providers and OpenAI-compatible HTTP adapter. |
| `app/infrastructure/persistence` | SQLite local adapter and PostgreSQL shared adapter/migrations. |
| `app/infrastructure/redis` | Redis rate limiting, prompt cache, and distributed singleflight. |
| `app/interfaces/http` | Auth dependencies, routes, SSE response, middleware, and exception mapping. |
| `app/core` | Configuration, lifespan, and dependency wiring. |

## Request lifecycle and routing

`POST /v1/chat` (and the compatibility chat-completions route) authenticates a configured client and calls `ChatService`. The service applies rate limiting, resolves a profile/candidate list, runs input guardrails, optionally checks the exact cache, and coalesces identical cache misses through local and optional Redis singleflight. On a miss it snapshots the shared budget, atomically reserves estimated capacity, and invokes routing/fallback. Provider retry policy, fallback triggers, provider request IDs, per-attempt status, and circuit state are represented in the decision trace/audit. Output guardrails run before the result is finalized. A successful response is not returned as successful until durable accounting/finalization succeeds.

The circuit breaker is process-local. Retry and fallback only apply to provider errors permitted by the profile policy; they do not retry database errors. Streaming may choose another provider only before the first non-empty client-visible message. Once output is emitted, the provider is pinned and a later failure is terminal for that stream.

## Budget, reservation, settlement, and receipt

The PostgreSQL adapter persists shared usage and reservation state; SQLite is the local/test adapter. A request reservation is lease-backed. `PostgresStreamingFinalizationRepository.finalize_stream` locks the reservation and, in one transaction, updates usage/reservation state, inserts request and provider-attempt audit, and writes the unique finalization receipt. Replaying a matching request/reservation payload returns the prior receipt; a payload mismatch is a conflict. Commit outcome uncertainty is not equivalent to rollback: the caller queries the receipt, and an unqueryable result remains uncertain for reconciliation.

The R10 change introduces a separate bounded `database_finalization` executor lane. The process still has eight synchronous-I/O workers total: three regular database workers, three finalization workers, one Redis worker, and one default worker. The finalization lane has a hard limit of 64 in-flight operations; it is not an unbounded queue. Receipt recovery and atomic finalization share that lane, while ordinary database reads/reservations use the regular database lane. Local queue saturation now has the `database_admission_overloaded` error code rather than being classified as PostgreSQL unavailable; a database dependency circuit-open remains `database_unavailable`.

This is a per-process limit. It is not a PostgreSQL connection pool: current repository operations open synchronous psycopg connections. Multi-replica capacity therefore multiplies worker/queue limits and must be checked against the database's connection budget. No controlled post-change capacity claim is made yet.

## AsyncIO and synchronous I/O

Repository and Redis ports are synchronous, so request paths use `BoundedBlockingIO` instead of calling them on the event loop. Each lane owns a bounded `ThreadPoolExecutor` and admission semaphore. Cancellation is deferred until an already-running function drains because Python cannot safely stop a transaction thread. Metrics expose active/in-flight/queued work, admission waits/rejections, operation execution totals/counts/maxima, and dependency-circuit state. Readiness probes use reserved probe workers so business saturation does not automatically pin `/live` or `/ready`.

The lane split protects already-admitted finalization work from ordinary database reads, but it cannot make a dead PostgreSQL server healthy. During an outage, dependency circuit and readiness behavior remain fail-fast. A request rejected by a full local lane is a capacity rejection, not proof of a database outage.

## Redis responsibilities

Redis is used for a shared sliding-window/global rate limit, optional exact response cache, and a lease-based distributed singleflight lock. Rate limiting is fail-closed when its configured shared authority is unavailable. Cache failures degrade to misses; singleflight can fall back to local coalescing. Local mode is process-scoped and must not be described as globally consistent. Redis does not own token budget, audit, settlement, or receipts.

## Health, observability, HTTP, and SSE

`/live` is a process liveness signal. `/ready` checks required database, Redis rate-limit, and provider state using bounded probes and recovery hysteresis. `/metrics` emits Prometheus text with low-cardinality labels. Phase timing, request/provider metrics, executor diagnostics, and optional OTLP tracing are implemented, but R08 remains partial until an external Prometheus/trace backend is queried end to end.

Buffered Chat responses are JSON. Streaming returns SSE events (`message`, `usage`, `done`, or `error`). The streaming service reserves before returning the session; generator completion/cancellation finalizes before emitting terminal accounting events. Client disconnect means delivery is not guaranteed, but does not undo already durable settlement. Partial output is never transparently retried on another provider.

## Container and release posture

The Dockerfile uses an immutable `python:3.12-slim` digest, a locked `uv.lock`, a non-root UID, and a minimal runtime stage. `deploy/wave5/compose.yaml` is a local isolated Gateway + PostgreSQL + Redis acceptance environment. The previous candidate image `sha256:44486db8…` was reproducible and passed runtime smoke, but it contains source `5a474c2`, not the current R10 source commit. A clean build from `4febd22` failed because Docker BuildKit could not complete TLS access to PyPI; no new image ID or vulnerability scan exists for `4febd22`.

## Decisions and known constraints

- Shared budget/audit are in PostgreSQL because multiple gateway processes must make one atomic admission/accounting decision.
- Redis owns high-rate coordination/cache concerns; it is not used as the accounting authority.
- The synchronous repository contract is isolated rather than called directly from AsyncIO handlers, but connection reuse/pooling is not implemented.
- Admission is bounded by lane and by process. Rejection is preferable to unlimited memory growth, but does not count as successful capacity.
- A healthy local test, green CI, or mock-provider throughput does not prove production provider performance or release readiness.
- Current formal release gates remain blocked by R04, R06, R08, R09, R10, and the Docker build failure for the latest source. See `evidence/wave5/release-closure/RELEASE_GATES_FINAL.json`.
