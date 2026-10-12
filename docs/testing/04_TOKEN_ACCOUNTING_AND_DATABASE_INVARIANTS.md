# Token accounting and persistence invariants

## Assertions exercised

- Baseline and final pytest used the repository's SQLite-backed fixtures. Existing token-budget tests cover single-use settlement, idempotent release, lease expiry/reconciliation, atomic finalization, rollback, and commit-ack-loss recovery.
- Hypothesis generated 8 valid Unicode requests over real loopback HTTP. Each successful request was checked against SQLite for exactly one request-audit row, one settled receipt and terminal `settled` reservation.
- The post-token Toxiproxy test checked one request audit row, one terminal settlement record, and reservation state `settled` after partial output followed by provider transport reset.
- Full pytest plus focused reliability tests passed; the exact counts and external logs are listed in `12_FINAL_TEST_ACCEPTANCE.md`.

## Database boundary

The local Windows full-suite run did not configure PostgreSQL or Redis, so its service-dependent cases were skipped. Separately, the pushed Linux GitHub Actions run executed isolated PostgreSQL repository/finalization probes and Redis adapter/two-replica probes successfully. PostgreSQL evidence includes cold-start reservation, a shared-budget race, idempotent finalization, audit rollback, orphan lease reclamation, migration replay, and TCP commit-ack-loss where the commit completed but its acknowledgement was dropped and the receipt was recovered directly. Redis evidence includes 10 admitted/10 rejected global rate-limit requests, shared-cache consistency, outage-policy classification, and two-replica singleflight/lease-expiry recovery.

This is bounded integration evidence, not complete PostgreSQL HA/failover or exhaustive Redis partition/recovery testing. The isolated PostgreSQL package coverage is 62% combined (connection module 60%, repository module 64%); Redis adapter coverage is 88% combined. The Toxiproxy provider-stream reset remains a separate local SQLite-backed scenario and was not run against PostgreSQL. Do not extrapolate these probes into general production exactly-once or HA guarantees.

Remote evidence identity: GitHub Actions Run `38201945812`, implementation commit `95574cd11d59f851e92baff2562a82263f32721e`; artifact `11725997608`. The exact raw JSON and package coverage reports are under `remote-ci/ci-evidence/postgres/` and `remote-ci/ci-evidence/redis/` in the external evidence root.
