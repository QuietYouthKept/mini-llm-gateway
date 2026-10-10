# Reservation / Receipt Invariants — observed contract

Status: PARTIAL; database integration probes pass, crash/transport edges remain unproven.

The PostgreSQL finalizer locks the reservation row, checks the existing receipt, applies budget and reservation state changes, records request audit and provider attempts, and inserts a finalization receipt in one database transaction. A replay with matching idempotency inputs returns the existing receipt; conflicting reuse is rejected. Expired-reservation reconciliation also locks expired rows and commits release receipt plus orphan audit in a transaction.

The observed lifecycle is `reserved → settled` for successful accounting and `reserved → released` for explicit release or expired orphan reconciliation. `settled`/`released` are terminal in the tested repository path. A failed transaction before commit leaves the reservation `reserved` and inserts no receipt/audit (verified with injected PostgreSQL triggers). A lost acknowledgement after a successful transaction is resolved by querying the durable receipt and replaying the same idempotent command; the probe observed one budget increment and one request row.

This is transactionally atomic and replay-safe within the tested contract, not proof that every network ambiguity or process-crash interleaving is exactly-once. A true TCP commit-ack loss and kill-at-commit test remain outstanding. Unknown outcomes must be queried/reconciled; clients must not blindly retry with a new idempotency key.
