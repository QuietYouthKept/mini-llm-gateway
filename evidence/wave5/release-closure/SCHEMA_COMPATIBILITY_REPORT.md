# Schema Compatibility Report

Status: NOT EXECUTED for cross-version compatibility.

The Wave 5.1 candidate applied/verified its migration ledger on a fresh isolated PostgreSQL 16 database and migration replay succeeded. No older committed application image was run against that same migrated schema during this turn. The local staging probe therefore establishes only candidate self-compatibility, not old/new expand-contract compatibility. Before a rollback drill, compare immutable migration checksums and run both binaries against the same schema in the required order.
