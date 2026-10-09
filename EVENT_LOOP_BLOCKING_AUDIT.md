# Event-loop blocking I/O audit — Wave 4

Review scope: local Wave 4 working tree on `codex/wave4-production-readiness`, based on HEAD `d8d8d2db1c8d0e3ec7ad32564d5f60148df4332f`. This is a code-path and isolated-staging audit, not a production availability certification.

## Call-chain findings

| Path | Blocking operations | Current execution | Bounds / cancellation semantics | Remaining concern |
|---|---|---|---|---|
| Non-stream chat | rate-limit adapter; budget snapshot/reserve; Redis cache/singleflight; budget finalization/receipt; request and attempt audit | Main chat path delegates sync adapters to container-owned `BoundedBlockingIO` | 8 worker threads, 16 in-flight admission limit, bounded admission; cancellation waits for the already-running worker before propagating to prevent a DB commit racing an assumed release | A worker blocked in the driver cannot be forcibly stopped; concurrent DB outage behavior remains inadequate |
| Streaming admission | rate-limit, cache, reserve and distributed singleflight | Delegated to the same bounded executor | Reserve/finalization operation is drained on cancellation; uncertain outcomes are not blindly released | Not every disconnect/DB outage interleaving is qualified at high concurrency |
| Streaming settlement | receipt-backed finalization plus audit/attempt write | Finalization runs off-loop through bounded executor; existing receipt/idempotency contract retained | Cancellation drains synchronous operation; committed result can be reconciled by receipt | Injected finalization failure preserved reservation and returned `stream_finalization_unknown`; hard-crash reconciliation needs more proof |
| HTTP audit / request lookup / admin maintenance | sync repository read/write, bootstrap/reconciliation | Delegated through executor (fallback `asyncio.to_thread` only if no container executor exists) | DB exception path marks audit skipped to avoid a second DB attempt; cancellation is not recorded as ordinary HTTP failure | Audit can be absent during outage; do not report it as durable success |
| Readiness | PostgreSQL schema probe; Redis ping; provider probe | Concurrent dependency probes, per-dependency serialization and bounded executor | PostgreSQL connect 1s, statement 3s, lock 1s; Redis socket/connect 2s | Actual 20-request DB outage failed readiness <=2s |
| Liveness | process-only endpoint | No DB/Redis call in endpoint | Returned 200 during outage load | Took 1.547s under the 20-request outage experiment, missing suggested <1s target |

## Driver and transaction semantics

`psycopg.connect()` is synchronous. PostgreSQL defaults now set a 1s connection timeout, 3s statement timeout, 1s lock timeout, and 5s idle-in-transaction timeout. These limits do not make an already-running Python worker cancellable. `BoundedBlockingIO.run()` shields and drains the worker on caller cancellation; this prevents cancellation from racing a late commit, but propagation waits for the driver call. The bounded pool contains resource use but cannot establish a hard end-to-end deadline for every OS/network failure.

Existing PostgreSQL repository transactions use context-managed connections/transactions and receipt-backed finalization. Tested normal success and commit-unknown paths use durable records; no in-memory flag is used as idempotency proof. Isolated probes confirmed selected receipt replay and atomic budget/request/attempt finalization paths, not every crash point.

SQLite and Redis adapters are synchronous too; the Wave 4 request paths touched here route their calls through the executor. Provider HTTP remains async. Config reload is offloaded. No separate synchronous DNS lookup was identified in the provider call path; runtime egress/SSRF controls remain unverified.

## Reproduction and outcome

Real isolated Docker Compose test: PostgreSQL 16 + Redis 7 + Gateway, 20 concurrent TCP requests during PostgreSQL outage. `/live` returned 200 in 1.547s; maximum request duration was 9.594s; `/ready` produced no response before the harness deadline (`readiness_status=0`, measured 3.172s); recovery readiness returned 200. Some requests timed out/returned errors; injected requests had zero reservation rows, while some HTTP audit rows appeared after recovery. The experiment failed suggested 5s dependency-request and 2s readiness targets. Raw evidence: `evidence/wave4/staging-acceptance-final.json`.

The executor change alone did **not** complete PostgreSQL outage isolation. The experiment does not establish that the event loop remained responsive under all load; DB/worker contention, audit fan-out and readiness scheduling remain plausible contributors. Do not claim P1 resolved.

## Required next work

1. Add per-dependency concurrency budgets and fast-fail circuit/open-state for DB-backed routes; avoid sending every outage request into a saturated queue.
2. Instrument executor queue wait, active workers, PostgreSQL acquire/query/commit latency and cancellation drain duration.
3. Re-run 20–50 TCP outage requests with <1s liveness, <=2s readiness and explicit <=5s dependency failure.
4. Exercise connection reset during reserve, settle and commit acknowledgement loss; assert reservation, receipt, budget, request log and attempt states in PostgreSQL.
5. Reconcile crash-left reservations after restart and demonstrate bounded lease recovery without treating unknown commits as releases.
