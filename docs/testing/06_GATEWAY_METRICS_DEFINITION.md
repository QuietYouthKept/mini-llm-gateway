# Gateway metrics and evidence definition

This execution did not add a new telemetry subsystem or claim operational metric coverage. The test artifacts report only bounded, low-cardinality aggregate dimensions needed to explain the executed scenarios:

| Measure | Definition | Source | Result availability |
|---|---|---|---|
| HTTP outcomes | Request count by status class/code for property probe | Hypothesis runner | Measured: 8x200, 2x422, 5x400 |
| Generated contract cases | Schema-generated cases and pass/fail count | Schemathesis JUnit/log | Measured: 127/127 passed |
| Stream chunks | Non-empty `message.delta` events parsed by client before injected RST | TCP scenario result JSON | Measured: 3 |
| SSE terminal event | Client-visible `error` or `done` event | TCP scenario result JSON | Measured: `error`; no `done` |
| Provider attempts | Attempt state and request count per synthetic provider | SQLite plus provider `/stats` | Measured: A=1 error; B=0 |
| Accounting terminal state | Final reservation/finalization and request-audit cardinality | SQLite | Measured in the bounded successful cases |
| Latency, RPS, CPU/RSS, queue wait | Requires repeated controlled load/telemetry sampling | Not run | NOT MEASURED; resource gate blocked load tests |
| PG connection/transaction wait | Requires isolated PostgreSQL instrumentation | Not run | NOT MEASURED; PG integration skipped |

Do not interpret this table as production observability coverage. The CSV companion contains only measurements from this round and explicitly labels unavailable metrics.
