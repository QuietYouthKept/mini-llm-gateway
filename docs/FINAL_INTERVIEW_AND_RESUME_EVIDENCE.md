# Final Interview and Resume Evidence

Evidence snapshot: 2026-10-10. Current R10 source commit: `4febd225a1e5fc1144cda0f4596a5af16242c2a9`. Use the wording below only with the stated boundaries; the current code has not yet been packaged into a newly built image or accepted at the original high-concurrency gate.

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
- R10 iteration 1 separates normal DB work from settlement/recovery capacity without increasing total process worker count. Local queue saturation is a distinct HTTP 503 classification, not mislabeled PostgreSQL outage. It is still awaiting an equivalent controlled load result and a new image build.

## D. Verified quantitative results and safe resume wording

Current GitHub CI Run 38026816922 tested commit `4febd22`: **207 passed**, **83.47% pytest-only branch coverage**, independent 80% gate passed. PostgreSQL integration/repository probe, Redis adapter probe, Redis two-replica HTTP, TCP HTTP/SSE, provider contract, Functional Eval, Security Eval, Secret Scan, Dependency Audit, Ruff, compileall, and hygiene all succeeded in that run. Evidence artifact `11660911166` and validation artifact `11660341651` report 155/155 files with no missing/extra/hash/size mismatch; manifest SHA-256 is `70233635a3cd4c476a9323be5252c98de3a66c4040011fd36758db1fa0a90689`.

The previous valid but uncontrolled-resource mock HTTP matrix on source `5a474c2` achieved 100% at concurrency 1 and 8, 90.71% at 32, and 33.61% at 64. At 32 it recorded 240 `database_unavailable` and 105 `stream_finalization_unknown`; at 64 it recorded 3,234 and 335 respectively. These are failures, not a capacity claim. A new controlled old/new comparison is running under 2 CPU/1 GiB Gateway and 2 CPU/1 GiB PostgreSQL limits (Redis 1 CPU/512 MiB). Until all cells finish and the matching new image is built, do not claim improved c32/c64 reliability.

Previous image `sha256:44486db8…` had two reproducible builds, non-root/read-only smoke, and 0 Critical / 44 High Trivy findings. That image tests source `5a474c2`, not current source `4febd22`; current image build failed in BuildKit dependency download with TLS EOF, while host direct PyPI worked. No current-source image digest or scan exists.

### Resume bullet (accurate now)

“Implemented a bounded PostgreSQL finalization lane and explicit admission-overload classification in a FastAPI LLM gateway; added executor-isolation and pre-submission/receipt regression tests. The source commit passed 207 CI tests at 83.47% branch coverage with PG/Redis/SSE evidence; the original c32/c64 performance gate remains under revalidation.”

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

A full local semaphore rejects work before it reaches the executor and now maps to `database_admission_overloaded`; an actual DB connect/operation error or database dependency circuit-open maps to `database_unavailable`. The finalization lane protects admitted settlements from ordinary DB queue pressure. It has a hard 64 in-flight limit and does not increase total workers. The capacity/performance gate remains failed until the matched load matrix validates the change.

### Why does green CI not imply production readiness?

CI validates a source commit under its runner topology. It does not prove the current source image builds reproducibly, clear OS-image vulnerabilities, test a real lost COMMIT ACK, validate external egress/DNS policy, or demonstrate capacity under production-like resources. At this snapshot R04 is failed (44 High on the old candidate), R06 not executed, R08/R09 partial, and R10 not yet remeasured after this fix.

See `docs/FINAL_SYSTEM_ARCHITECTURE.md`, `docs/FINAL_CORE_CALL_CHAINS.md`, `docs/FINAL_OPERATIONS_RUNBOOK.md`, and `evidence/wave5/release-closure/EVIDENCE_INDEX_FINAL.md` for source/evidence navigation.
