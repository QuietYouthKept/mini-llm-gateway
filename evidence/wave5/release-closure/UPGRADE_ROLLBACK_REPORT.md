# Upgrade / Rollback Report

Status: FAILED release gate (actual old→new→old drill not executed).

## Executed on candidate only

The isolated project `wave51-release-closure` ran candidate image `sha256:9c85a88d…` against disposable PostgreSQL 16 and Redis 7. Startup verified the migration ledger; `/live` returned 200; `/ready` returned 200 after dependency health checks; a real TCP SSE request returned message/usage/done and left one settled reservation, one `settle` receipt and one request audit. Compose stopped the candidate normally: exit code 0, OOM false, and Uvicorn logged application shutdown complete. Restarting the same candidate restored `/ready` 200.

## Not executed

No older committed image was run against this database, so no schema compatibility comparison or old→new→old health rollback was demonstrated. The successful same-version restart is only a process restart. It is not rollback. Do not deploy or roll back based on this report; complete `UPGRADE_ROLLBACK_MATRIX.json` with two immutable image digests and database-level assertions first.
