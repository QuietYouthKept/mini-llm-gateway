# Contributing

Use Python 3.11+, create a virtual environment, and install `.[dev]`. Run
`make lint`, `make test`, `make eval`, and `make security-eval` before opening
a change. `scripts/verify.py` runs the same local release gate with the active
interpreter.

Keep domain code independent from FastAPI and backend libraries. Provider
adapters implement `ProviderPort`; persistence and shared state implement a
port in `app/domain/ports`.

Every behavior change needs a test that answers: **what claim does this test
prove?** Include failure/cancellation semantics for code that owns a lease,
reservation, connection, or retry loop. Never add real secrets, datasets, or
generated database files to the repository.
