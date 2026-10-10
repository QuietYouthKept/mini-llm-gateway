# PostgreSQL Failure Isolation Design

## Implemented and exercised

- Business synchronous work uses bounded dependency lanes. PostgreSQL failures cannot consume Redis or default-lane worker capacity.
- Readiness has four dedicated bounded probe workers, coalesces concurrent refresh requests, applies a 0.8-second async deadline, and returns fail-closed `checking` or dependency failure state. Probe calls respect the business circuit and use a single half-open probe.
- Liveness performs no dependency check. In the real TCP experiment it remained HTTP 200 within 32 ms during SIGKILL PostgreSQL outages at 20 and 50 concurrent requests.
- The PostgreSQL DNS workaround caches the address for a single host and refreshes asynchronously after connection errors; `host` remains present for TLS identity checks.
- Network failures and circuit-open/admission failures are treated as database unavailable. The request path does not claim durable audit when the database is down, records audit failure metrics, and wakes same-key local singleflight followers.
- Existing worker operations are not cancelled just to return a fast HTTP response. `BoundedBlockingIO` drains submitted work before propagating cancellation.

## Measured boundary

The valid isolated SIGKILL matrix is in `pg-outage-p1-isolated-repeat3.json`. Every request returned classified 503 within 2.56 seconds maximum; `/ready` returned 503 within 0.781 seconds; `/live` returned 200 below 0.032 seconds. No request audit or budget reservation existed for the rejected requests. The probe restarted PostgreSQL between repetitions and waited for readiness before querying persisted state.

## Not established

- Commit outcome unknown after a lost acknowledgement is not covered by this outage matrix.
- Cancellation while an actual PostgreSQL write is executing, hard process kill during settlement, and recovery/reconciliation after those exact interleavings still need dedicated database tests.
- DNS refresh is process-local, assumes a single hostname, and may take the host resolver's full timeout on its one background thread. There is no explicit cache cardinality cap.
- PostgreSQL connect/statement/commit duration and DB lock-wait histograms are not yet independently exported as dedicated metrics. Current evidence has bounded executor timings and aggregate HTTP timings, not complete database phase instrumentation.
- CPU, RSS, and container throttling were not measured in the outage experiment.
