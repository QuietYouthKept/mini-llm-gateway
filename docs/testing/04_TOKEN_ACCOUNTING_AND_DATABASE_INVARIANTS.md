# Token accounting and persistence invariants

## Assertions exercised

- Baseline and final pytest used the repository's SQLite-backed fixtures. Existing token-budget tests cover single-use settlement, idempotent release, lease expiry/reconciliation, atomic finalization, rollback, and commit-ack-loss recovery.
- Hypothesis generated 8 valid Unicode requests over real loopback HTTP. Each successful request was checked against SQLite for exactly one request-audit row, one settled receipt and terminal `settled` reservation.
- The post-token Toxiproxy test checked one request audit row, one terminal settlement record, and reservation state `settled` after partial output followed by provider transport reset.
- Full pytest plus focused reliability tests passed; the exact counts and external logs are listed in `12_FINAL_TEST_ACCEPTANCE.md`.

## Database boundary

PostgreSQL was not configured in this execution and its integration tests were skipped. Therefore these results do not establish PostgreSQL locking, transaction isolation, commit-unknown resolution, multi-instance consistency, or PostgreSQL behavior during the Toxiproxy fault. Redis integration and cross-instance consistency were likewise not run. Do not extrapolate SQLite results into database HA or distributed exactly-once guarantees.
