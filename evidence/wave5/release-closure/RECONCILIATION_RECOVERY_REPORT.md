# PostgreSQL Reconciliation / Recovery Report

Status: PARTIAL.

`scripts/postgres_integration_probe.py` ran against the isolated PostgreSQL service inside Compose and exited 0. It ran migrations twice, tested concurrent warm/cold budget rows, injected audit and finalization rollback failures, replayed a finalization concurrently, simulated acknowledgement loss after the database call committed, then queried the durable receipt, reservation, usage and audit rows. It also expired a lease and ran reconciliation twice through the service contract.

Observed results: migration replay succeeded; budget bounds held; rollback left no partial audit/receipt and reservation remained reserved; synthetic post-commit acknowledgement loss recovered a settled receipt; replay did not double-charge; concurrent finalization produced one request row; an orphan was released with one audit and release receipt.

Raw evidence: `postgres-integration-probe.json` and `postgres-integration-probe.exitcode`.

Limit: the acknowledgement-loss test injects an exception after the real repository returns. It does not sever the PostgreSQL socket after server commit, kill the process at the commit boundary, or test competing reconciliation across replicas. Those are required before production recovery claims.
