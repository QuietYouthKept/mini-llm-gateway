# Wave 5.2 PostgreSQL COMMIT acknowledgement boundary

Status: **NOT VERIFIED**.

No protocol-aware TCP proxy or server-side fault injection dropped the PostgreSQL `COMMIT` acknowledgement after the server committed. The passing PostgreSQL integration probe's Commit Unknown case is synthetic: it injects an exception after the repository commit returns and then resolves the receipt by querying durable state. That is useful idempotency/replay coverage, but is not wire-level proof.

The separate PostgreSQL SIGKILL outage probe tests database unavailability before requests can commit; all six 20/50-concurrency outage rounds returned explicit 503s, preserved `/live`, returned `/ready` 503, created no request audit or reservation, and recovered after PostgreSQL restarted. This likewise does not exercise a lost commit acknowledgement.

Required follow-up: add a reviewed protocol-aware fault proxy that can identify the backend `ReadyForQuery` response to COMMIT and sever the client connection at that boundary. Run Reserve, Settlement, Receipt-write, process-kill, concurrent replay/reconciliation, and two-replica cases, querying reservation state, finalization receipt, token budget, request log, and provider attempts after each injection. Until that wire-level test exists, do not claim Commit Unknown is closed.

Evidence: `postgres-integration-probe.json`, `wave52-pg-outage-probe.json`, `wave52-postgres-after-recovery.txt`, and the retry/reconciliation invariant reports in this directory.
