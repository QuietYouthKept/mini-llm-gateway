# Resume Claims — Evidence-Bound Draft

These bullets describe real engineering work already present in the repository and the additional verified evidence produced by this sprint. Keep the qualifiers; do not describe local probes as production deployment.

## LLM Infrastructure / Backend Engineering

- Built a bounded synchronous-I/O isolation layer for an async LLM gateway, separating regular PostgreSQL work from finalization and Redis lanes; retained cancellation draining so worker-side commits cannot race asynchronous cleanup.
- Implemented idempotent streaming settlement with durable finalization receipts and atomic request/attempt auditing. Added a real PostgreSQL TCP fault probe that forwards `CommandComplete(COMMIT)` and drops the following protocol acknowledgment; verified client-side `OperationalError`, direct receipt recovery, settled reservation, exactly one audit and provider attempt, and 12 tokens billed exactly once.
- Instrumented HTTP request ID, route and response status in the trace root, and added dependency/lane/operation spans around bounded PostgreSQL and Redis work. Queried an exported request trace from Jaeger and matched the request ID to DB/Redis spans; verified the Prometheus scrape target and query API against a local isolated stack.
- Exercised Redis behavior across two Uvicorn replicas: 20 concurrent requests produced 10 admissions and 10 rate-limit rejections; distributed singleflight produced one provider execution with equivalent cross-replica responses; shared PostgreSQL budget race returned one 200 and one 429 with one settled reservation.
- Added a fully offline, deterministic portfolio CLI that exercises normal chat, provider fallback, streaming SSE, request audit, and metric exposition against temporary SQLite and mock providers; an optional mode can target the running HTTP service.

## Project impact numbers — historical only

The following are previously measured R10 source-overlay results, not a benchmark of this sprint: at concurrency 64 success rate moved from 28.42% to 80.08%; at concurrency 32 it moved from 80.35% to 71.02%. Include them only when prepared to explain admission rejections, resource isolation trade-offs and why R10 was not declared PASS. The raw evidence and methodology must accompany the claim.

## Interview-safe boundaries

- “Commit acknowledgment loss was injected over a real TCP proxy” is accurate. “A production database failed over successfully” is not.
- “Trace and metric query paths were verified locally” is accurate. “Production SLO alerting is operational” is not.
- “Redis two-replica probe passed” is accurate. “Horizontal scaling is production-ready” is not.
- “I added no performance optimization in this sprint” is accurate; do not attribute the historical c32/c64 figures to the new trace/probe changes.
- `RELEASE_READY` remains **false** until every required R01–R11 release gate has independent passing evidence.
