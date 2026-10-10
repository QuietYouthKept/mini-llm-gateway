# Final Core Call Chains

Source snapshot: `4febd225a1e5fc1144cda0f4596a5af16242c2a9`. Functions below are current names in the source tree. The linked CI and integration evidence verifies the code commit, while R10 load testing and a matching built image remain unverified.

## 1. Normal buffered Chat

`POST /v1/chat` → `app/interfaces/http/routes/chat.py` → auth dependency resolves `ClientConfig` → `ChatService.execute` → Redis/memory rate limiter → profile/input guardrail → exact cache and local/distributed singleflight → `TokenBudgetService.snapshot` + `reserve` → `RoutingService.resolve_candidates` / fallback service → provider adapter → output guardrail → `_finalize_stream(operation="settle")` → `PostgresStreamingFinalizationRepository.finalize_stream` transaction → cache put/audit response.

The durable transaction couples reservation state, usage, request audit, provider attempts, and receipt. Provider failure before invocation releases the reservation; failure after a provider attempt records an error and finalizes according to the current accounting path. Database outage skips secondary request-path audit attempts; it is not rewritten as success. Relevant evidence: `tests/integration/test_chat_api.py`, `tests/unit/test_streaming_failure_semantics.py`, PostgreSQL probe in CI Run 38026816922.

## 2. SSE stream

`POST /v1/chat` with `stream=true` → `chat.py` → `ChatService.start_stream` authenticates policy/rate-limits/reserves before returning `StreamingSession` → `_stream_events` invokes provider stream and yields `message` events → on normal completion it calls `_finalize_stream(settle)` → emits usage then `done`.

The database receipt is written before terminal success is yielded. Streaming is uncached. Relevant evidence: `tests/unit/test_streaming_failure_semantics.py`, `tests/integration/test_http_sse_e2e.py`, CI artifact `11660911166`.

## 3. Provider timeout and fallback

Provider adapter raises a typed timeout/failure → retry policy checks retryable error and count → circuit records failure → fallback policy checks configured trigger and next eligible provider → each attempt retains provider ID/request ID/status in the decision trace → eventual success settles once, or terminal failure finalizes/releases once.

Fallback is provider policy, not a response to database admission rejection. After first emitted SSE message, provider switch is prohibited. Relevant tests: `tests/unit/test_fallback_service.py`, streaming fallback cases in `tests/unit/test_streaming_failure_semantics.py`; provider contract result in CI.

## 4. Reservation to settlement and receipt

`snapshot` → `try_reserve_token_budget` (atomic database admission + lease) → provider → finalization lane → `finalize_stream` locks reservation → updates usage and reservation state → inserts request log/attempts → inserts unique receipt → commit → response uses receipt's `budget_after`.

Matching replay returns the existing receipt without duplicate usage. Mismatched payload conflicts. A PostgreSQL probe injects a synthetic post-commit exception and recovers by receipt lookup; this is not the real lost-COMMIT-ACK network fault required by R06. Evidence: `scripts/postgres_integration_probe.py`; raw CI result under the downloaded R10 run artifact.

## 5. Redis cache hit

Rate limiter → cache key calculation → Redis exact-cache lookup → cache hit returns stored response without provider call or new budget reservation; request audit records cache metadata/cost-saved signal. A Redis outage turns cache access into a miss, not fabricated success. Evidence: Redis adapter integration and `tests/integration/test_chat_api.py` cache cases.

## 6. Distributed singleflight

Cache miss → local singleflight → Redis owner-safe lease when enabled → owner obtains/reserves/calls provider/finalizes/cache-writes → followers await publication and re-check cache → release lease in `finally`; TTL handles crashed owners. Redis failure falls back to local coordination. It is not a replacement for a database receipt. Evidence: Redis adapter/two-replica probes in CI Run 38026816922.

## 7. PostgreSQL outage and fast-fail

Repository connection/operation failure → worker marks the database dependency circuit open → later calls fail before opening more connections → `/ready` reports not ready, `/live` remains process-live → HTTP request returns explicit 503 without pretending an audit/reservation succeeded → recovery probe succeeds and readiness hysteresis restores service.

The R05 candidate probe ran 20/50 concurrent SIGKILL cases, three repetitions each, and passed. That probe was against image `5a474c2`; it must be repeated against a new built image after the current source change. Evidence: `wave52-pg-outage-probe.json`.

## 8. High concurrency and bounded admission

HTTP tasks → regular DB lane for snapshot/reserve/read operations; atomic settlement/receipt/recovery use the separate `database_finalization` lane. Total worker count remains 8, with a hard 64-in-flight ceiling on finalization. `BlockingIOOverloadedError` before executor submission maps to `database_admission_overloaded`; it does not trigger a misleading receipt query. A dependency circuit-open is still `database_unavailable`.

R10's old same-unbounded-resource baseline failed at c32/c64. The current code passed unit/CI/integration gates, but the matching controlled performance matrix is in progress and the new image is not yet built. Therefore the lane split is a tested code change, not yet an accepted capacity result.

## 9. Client cancellation

ASGI cancellation/stream generator close → active provider attempt is cancelled/drained → if a provider ran, observed output is settled; otherwise reservation is released → if finalization outcome is unknown, no blind second settlement/release is assumed and the lease/receipt recovery contract applies. A cancellation after durable finalization cannot reverse it. Evidence: `tests/unit/test_streaming_failure_semantics.py`, TCP SSE E2E result.

## 10. Reservation reconciliation

Admin-authenticated maintenance endpoint → `TokenBudgetService.reconcile_expired_reservations` → PostgreSQL locks expired `reserved` rows → transaction inserts orphan audit + release receipt and changes state to `released` → subsequent runs can inspect counts. Reconciliation is crash recovery, not normal-load queue control. The prior 614-row cleanup happened only after the failed old load and does not erase that failure. Evidence: PostgreSQL integration probe and old run's `wave52-postgres-after-recovery.txt`.
