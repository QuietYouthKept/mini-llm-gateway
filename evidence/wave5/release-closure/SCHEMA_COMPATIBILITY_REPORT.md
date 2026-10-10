# Schema Compatibility Report

Status: NOT EXECUTED for cross-version compatibility.

The Wave 5.1 candidate applied/verified its migration ledger on a fresh isolated PostgreSQL 16 database and migration replay succeeded. No older committed application image was run against that same migrated schema during this turn. The local staging probe therefore establishes only candidate self-compatibility, not old/new expand-contract compatibility. Before a rollback drill, compare immutable migration checksums and run both binaries against the same schema in the required order.
# Wave 5.2 addendum — 2026-10-10

The prior Wave 5.1 statement above is superseded for the selected pair by a real isolated old→new→old drill. Old commit `c4ba57dafd380ca1d1a6ba39b40de0732d30a697`, new commit `5a474c208d3095e678469f307a7c7d549233e6b9`: `git diff c4ba57d..5a474c2 -- app migrations` is empty. Both images served `/ready` 200, Chat 200, and the Gateway SSE terminal `event: done` against the same PostgreSQL 16 / Redis 7 state. The migration ledger held seven entries. After rollback, six reservations were settled with six finalizations and six provider attempts, zero missing finalizations, and zero duplicate finalization keys.

This supports compatibility for this exact image pair and schema, not arbitrary future migrations. See `UPGRADE_ROLLBACK_MATRIX_WAVE52.json`, `ROLLBACK_FINAL_RESULT_WAVE52.md`, and `wave52-rollback/`.
