# Resume-ready results (evidence-bounded)

## Backend reliability / QA

- Expanded the gateway's deterministic streaming fault coverage with a real loopback TCP + Toxiproxy reset-after-output case; verified the client received 3 chunks then an SSE `provider_failed`, no `done`, no Provider B fallback, one audit row and one settled reservation.
- Added bounded property and generated API-contract validation: 15 Hypothesis-driven HTTP inputs with persistent accounting assertions on all 8 successes, plus 127/127 Schemathesis cases across two Chat API operations.
- Final local test suite: 242 passed, 6 skipped; pytest-only branch coverage 81.37%, with an independent `coverage report --fail-under=80` gate passing.

## Security / data evaluation

- Ran the repository's Security Eval (8/8) and aggregate-only local guardrail evaluation over 662 Parquet rows; dataset provenance, license and label semantics remain unverified, so no accuracy or model-safety claim is made.

## Mandatory wording limits

These are test counts, not production availability or customer throughput. No RPS, latency, concurrency, PostgreSQL/Redis HA, Docker vulnerability clearance, ASVS compliance, or release-ready claim is supported by this wave. Use “SQLite-backed local test” rather than implying PostgreSQL persistence for the new TCP reset case.
