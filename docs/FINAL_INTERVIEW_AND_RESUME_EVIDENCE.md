# Final Interview and Resume Evidence
Evidence snapshot: 2026-10-10. Current R10 source commit: `c9ddbe65f94f460a55cad07fe78c5e6b061f6dc4`; tree `322a6116f590cdaf55cad07fe78c5e6b061f6dc4`. Latest verified CI [Run 38030118570](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38030118570) ran against documentation snapshot `57705e9f135b00e3f48403f565ff35262d023362`, containing that unchanged source. Source remains unbuilt as a new container image and has not passed the high-concurrency R10 gate.

## A. One-sentence project description

Built a single-tenant LLM gateway that applies provider routing/fallback, shared token-budget accounting, Redis coordination, audit receipts, and HTTP/SSE controls around configurable LLM backends.

## B. Actual technology stack

Python 3.11/3.12, FastAPI, Uvicorn, asyncio, Pydantic, SQLite, PostgreSQL with psycopg, Redis, Prometheus text metrics, optional OpenTelemetry OTLP tracing, Docker/Compose, pytest/pytest-cov, Ruff, GitHub Actions, and a locked `uv.lock`. Deterministic mock/fake providers are used for tests and local load work; OpenAI-compatible HTTP providers are available through configuration.

## C. Engineering work worth discussing

- Async request orchestration over synchronous repositories, isolated with bounded executor lanes and cancellation drain semantics.
- Shared budget reservation and transaction-backed settlement receipt, with unique request/reservation idempotency and orphan reconciliation.
- Redis global rate limiting, exact cache, and lease-based distributed singleflight, each with a distinct outage policy.
- Provider attempt traceability, retry/fallback policy, process-local circuit breakers, output guardrails, and SSE behavior before/after first token.
- Commit-bound CI evidence with JUnit, independent pytest-only coverage gate, PostgreSQL/Redis adapters, HTTP/SSE, provider contract, evals, dependency and secret checks, and a manifest hash validator.
- R10 iterations 1–2 reserve bounded capacity for settlement/recovery without increasing total process worker count, route cancellation/generic-error recovery through finalization, and distinguish local database admission overload from PostgreSQL outage or unknown finalization. Regression tests and source CI pass; the matched-resource result is informative but fails the R10 capacity gate, and a current-source image has not been built.

## D. Verified quantitative results and safe resume wording

GitHub Actions [Run 38030118570](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38030118570) completed successfully: **208 passed**, **83.47% pytest-only branch coverage**, independent coverage gate passed. Ruff, compileall, PostgreSQL integration/repository probe, Redis adapter probe, Redis two-replica HTTP, TCP HTTP/SSE, Provider Contract, Functional Eval, Security Eval, Secret Scan, Dependency Audit, and hygiene succeeded. Evidence Artifact [11662136747](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38030118570/artifacts/11662136747) and Validation Artifact [11662026960](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38030118570/artifacts/11662026960) were uploaded; CI manifest covered 155 files and workflow validation passed. Manifest SHA-256: `1fbfdd94dbe4f73107f36b5541261ecfd007eece939244396b4aa562978cef9`.

The completed matched-resource mock HTTP comparison used identical configuration and seed with 2 CPU/1 GiB Gateway and PostgreSQL limits and 1 CPU/512 MiB Redis limits. At concurrency 32, success changed from **80.35% to 71.02%** (after leg: 1,113 explicit bounded admission rejections, zero `database_unavailable` and zero `stream_finalization_unknown`). At concurrency 64, success changed from **28.42% to 80.08%** (after leg: 816 bounded admission rejections, zero database-unavailable/unknown-finalization errors). The after-source c64 maximum P99 was 5,565 ms. The after leg mounted source `c9ddbe6` read-only over the previous image; it is not a new image result. This demonstrates accounting/error-classification improvement but leaves a material capacity/tail-latency issue; R10 did not pass.

Previous image `sha256:44486db8bb69095129d72cb1303937df117d968ffae703b8e3055a021fd5dacf` had two reproducible builds, non-root/read-only smoke, and 0 Critical / 44 High Trivy findings. It tests source `5a474c2`, not current source `c9ddbe6`. Current-source BuildKit dependency download failed with TLS EOF. No current-source image digest, reproducibility result, or image scan exists; the 44 High findings belong to the previous image.

### Resume bullet (accurate now)

“Implemented bounded PostgreSQL settlement isolation and idempotent finalization recovery in a FastAPI LLM gateway, with explicit admission-overload versus database-failure semantics and cancellation-path regression coverage. The source passed 208 CI tests at 83.47% pytest-only branch coverage with PostgreSQL/Redis/SSE evidence. A matched-resource source-overlay diagnostic improved c64 success from 28.42% to 80.08%, while c32 was 71.02%; R10 remains failed and the current source has no built image.”

Do not write “production-ready”, “64 concurrent requests supported”, “exactly-once provider calls”, “zero vulnerabilities”, or “R10 fixed” based on current evidence.

## E. Interview questions and project-specific answers

### Why can synchronous I/O block an AsyncIO server?

An `async def` handler only yields when it awaits cooperative work. A synchronous psycopg/Redis call blocks the event-loop thread if invoked inline. This project routes synchronous ports through `BoundedBlockingIO`, whose worker lane and semaphore cap concurrency. The event loop can continue serving unrelated requests, while cancellation waits for an in-flight DB function to finish because Python cannot safely stop its thread. Source: `app/application/services/blocking_io.py`; tests: `tests/unit/test_blocking_io.py`.

### Why not cancel a running database thread when the client disconnects?

The client task can be cancelled while the DB worker has already sent statements or is waiting for COMMIT. Forcefully pretending the operation stopped would turn an unresolved transaction into a false rollback assumption. The adapter drains in-flight work before propagating cancellation; a genuinely ambiguous commit requires receipt lookup/reconciliation. Source: `BoundedBlockingIO.run`, `ChatService` cancellation branches; evidence: PostgreSQL integration probe and streaming failure tests.

### What is Commit Unknown here?

The application sent a transaction and lost the response that would tell it whether COMMIT succeeded. The transaction may have committed. The gateway checks the unique finalization receipt by reservation ID and validates request, operation, and payload fingerprint. If it cannot query the DB, it reports uncertainty and preserves the lease for recovery. Current CI's synthetic post-commit exception tests this recovery logic, but R06 still needs a real dropped PostgreSQL COMMIT acknowledgement.

### How does settlement avoid duplicate billing?

The finalization repository locks the existing reservation, checks for an existing receipt, and in one DB transaction changes reservation/usage, writes request and attempt audit, and inserts a unique receipt. A matching replay returns the existing receipt; changed payload conflicts. This gives idempotent gateway accounting, not exactly-once execution at the provider.

### What belongs in PostgreSQL versus Redis?

PostgreSQL is the durable shared accounting/audit authority: budgets, reservations, receipts, request/attempt records, and migrations. Redis handles high-rate shared coordination: rate limit, optional cache, and distributed singleflight. Cache failure can degrade to miss; rate limiting is fail-closed; Redis does not decide billable usage.

### Why use Singleflight as well as a cache?

A cache avoids repeating a completed request. Singleflight suppresses simultaneous identical misses before a value exists. The Redis lease coordinates replicas; local in-process singleflight still helps one process. Neither is a budget lock or settlement receipt.

### How is bounded backpressure different from a database outage?

A full local semaphore rejects work before it reaches the executor and now maps to `database_admission_overloaded`; an actual DB connect/operation error or database dependency circuit-open maps to `database_unavailable`. A bounded finalization lane protects admitted settlements without increasing the worker count. The matched matrix confirms reduced c64 database/finalization failure classifications but still shows c32 admission rejection and c64 tail latency; the gate remains failed, and the current-source image is unbuilt.

### Why does green CI not imply production readiness?

CI validates a source commit under its runner topology. It does not prove the current source image builds reproducibly, clear OS-image vulnerabilities, test a real lost COMMIT ACK, validate external egress/DNS policy, or demonstrate production-like capacity. At this snapshot R04 is failed (44 High on the previous candidate), R06 not executed, R08/R09 partial, and R10 remains failed after the measured matched-resource comparison.

See `docs/FINAL_SYSTEM_ARCHITECTURE.md`, `docs/FINAL_CORE_CALL_CHAINS.md`, `docs/FINAL_OPERATIONS_RUNBOOK.md`, and `evidence/wave5/release-closure/EVIDENCE_INDEX_FINAL.md` for source/evidence navigation.
