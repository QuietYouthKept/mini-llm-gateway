# Release Rollback Runbook — Wave 5.1 acceptance status

Status: NOT EXECUTED as an actual rollback.

1. Preserve the failed/current release evidence and inspect readiness plus PostgreSQL migration ledger.
2. Stop new traffic, but do not delete PostgreSQL or Redis state.
3. Verify the prior image digest and schema compatibility report; never rely on a mutable tag alone.
4. Start the prior image against the same stateful services and verify `/live`, `/ready`, TCP Chat/SSE, reservation, receipt, audit, attempts and migration ledger.
5. If the old binary cannot read the newer schema, keep the forward-compatible schema and perform forward recovery; do not downgrade/drop data.
6. Record image digest, timestamps, HTTP results and DB row counts before reopening traffic.

This runbook is procedural guidance only. No old-version rollback was executed, and rollback must remain marked failed/unproven until the matrix is completed.
