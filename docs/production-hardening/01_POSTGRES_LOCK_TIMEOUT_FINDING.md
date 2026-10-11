# PostgreSQL lock-timeout finding

## Finding

On 2026-10-11, a controlled advisory transaction lock was held for five seconds on the same `(client_id, period)` key used by the token-budget reservation function. Under eight same-client requests, all eight returned HTTP 503. Live PostgreSQL samples showed `Lock:advisory` waits with a blocking PID; server logs reported SQLSTATE `55P03` (`lock_not_available`) after the configured one-second lock timeout. The requests had no provider attempt or committed reservation, consistent with failure before budget admission.

The old error classifier treated all Psycopg `OperationalError` values as dependency failures. `55P03` is a subclass of that family, so a healthy PostgreSQL instance with one contended client key opened the process-wide database circuit. A first cross-client control, run while that circuit was still open, was rejected without database mutation. After restarting only the isolated Gateway, the same cross-client control completed 8/8 requests with request audits, settled reservations, receipts, and provider attempts. This separates the client-scoped PostgreSQL lock from the process-wide circuit side effect.

The injected lock timeout is a reproduced failure mechanism. It does **not** establish that the historical overnight 1,984/1,984 503 cell had this cause: the historical run lacks failure-time SQLSTATE, blocking PID, and wait-event data.

## Candidate change

- `55P03` is excluded from `BoundedBlockingIO` dependency-circuit failure detection, including when nested in an exception cause/context chain.
- `ChatService` classifies it separately as retryable `database_lock_timeout` (HTTP 503), not `database_unavailable`.
- Request paths record the scoped failure in request audit and error metrics when the database can still accept the audit.
- Finalization still queries its idempotency receipt first. Only a completed receipt lookup that returns no matching receipt permits reclassification as a definite lock timeout; an unavailable receipt lookup remains `stream_finalization_unknown`.
- A committed receipt remains authoritative and is not rewritten as a failure because later delivery fails.

## Real PostgreSQL verification

The fixed image was tested against the isolated PostgreSQL 16 / Redis 7 / Gateway Compose project. During the bounded lock hold, eight requests alternated between `demo-key` (the contended `demo-client`) and `burst-key` (uncontended `burst-client`):

| Client group | Requests | HTTP/error | Durable state |
| --- | ---: | --- | --- |
| Contended `demo-client` | 4 | 4 × `503 database_lock_timeout` | 4 error request audits; no reservation, receipt, or provider attempt |
| Uncontended `burst-client` | 4 | 4 × 200 | 4 success audits, settled reservations, receipts, and provider attempts |

Without restarting the Gateway after that lock test, a subsequent same-client batch completed 8/8 successfully. This demonstrates that `55P03` no longer poisons the global database circuit in this synthetic scenario.

The final-source image was then tested at 20 and 50 concurrent TCP requests against the same held client lock, while `/live` and `/ready` were polled throughout:

| Concurrency | HTTP outcome distribution | Request audit | Reservations / receipts / attempts | Max sampled `/live` or `/ready` latency |
| ---: | --- | ---: | --- | ---: |
| 20 | 8 × `database_lock_timeout`; 12 × `database_admission_overloaded` (all 503) | 20 rows | 0 / 0 / 0 | 91.36 ms |
| 50 | 8 × `database_lock_timeout`; 42 × `database_admission_overloaded` (all 503) | 50 rows | 0 / 0 / 0 | 72.77 ms |

All health probes returned HTTP 200. This validates fast bounded rejection and health endpoint responsiveness under this controlled lock-contention scenario. It is not a database process-outage test, not a successful 20/50-request capacity result, and not an RPS benchmark.

A separate graceful PostgreSQL stop/start outage was also run against the same disposable Compose database (its named data volume was preserved):

- While PostgreSQL was stopped, 20 concurrent requests returned 8 `database_unavailable` and 12 `database_admission_overloaded` responses (all HTTP 503). At 50 concurrent requests, all 50 returned `database_unavailable`.
- The probe could not take its normal in-flight DB snapshot while PostgreSQL was down (`ConnectionTimeout`). After PostgreSQL restarted and recovered, read-only queries showed zero request logs, reservations, receipts, or provider attempts for either outage batch.
- Gateway `/ready` recovered to HTTP 200 without restarting the Gateway, and a subsequent same-process 8-request batch completed 8/8 successfully.
- A later global DB snapshot surfaced two expired `reserved` rows created intentionally by the earlier PostgreSQL probe's rollback cases. Their IDs and pre-reconcile state were saved first. The reconciler released exactly those two, writing the expected `reservation_lease_expired` audit rows and release receipts. Final DB totals were 364 settled, 3 released, 0 reserved.

This demonstrates recovery after a graceful database process outage and confirms the outage requests did not create accounting side effects. It does not validate abrupt SIGKILL/recovery, replica failover, or outage-time `/live`/`/ready` latency under the same 20/50 run.

Machine-readable reports and command exit codes are stored outside the repository:

- `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z\pg-diagnostic\induced-lock-55p03-fixed-mixed-clients.json`
- `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z\pg-diagnostic\post-lock-same-process-recovery.json`
- `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z\pg-diagnostic\lock-contention-c20.json` and `lock-contention-c20-health.json`
- `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z\pg-diagnostic\lock-contention-c50.json` and `lock-contention-c50-health.json`
- `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z\pg-diagnostic\pg-down-c20.json`, `pg-down-c50.json`, and `postgres-outage-reconciled-verification.json`
- `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z\pg-diagnostic\induced-lock-55p03-postgres-log-extract.txt`
- Docker build log and exit code: `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z\gateway-image-lock-timeout-build.log` and `.exitcode`

The proxy used for the final-source candidate Docker build was `http://host.docker.internal:7890`; TLS verification remained enabled. The final candidate image identity is recorded in `gateway-image-final-identity.txt`.

## Limits and follow-up

- This is a bounded causal injection, not a formal capacity or throughput benchmark.
- The historical outage remains un-attributed until reproduced with the original conditions and contemporaneous server evidence.
- The real PostgreSQL tests exercise the synchronous chat path; streaming admission/finalization classification has unit coverage but still needs a stream-specific real-PG lock injection test.
- PostgreSQL synchronous calls remain bounded by worker lanes but still need separate latency/failure-isolation validation under connection exhaustion, server restart, and many simultaneous clients.

## Container acceptance boundaries

The running final-source candidate (`sha256:42935410d1bee19ec864c038b092091f1c9b9f94673deae5f30491aafcad4072`) passed local runtime checks: UID/GID `10001:10001`, read-only root filesystem, all capabilities dropped, `no-new-privileges`, `/app` write denied, `/tmp` write succeeded, Docker health status healthy, and graceful SIGTERM exited with status 0 before a healthy restart. Raw values are in `final-gates\container-security-and-health.txt` and `container-sigterm-exit.txt`.

One clean no-cache repeat used the same source SHA, pinned base digest, lockfile, build date, and proxy `7890`. The top-level image identity differed (`429354…` versus `e208f0…`); the first five rootfs layers matched and the remaining five differed. The image reproducibility gate is therefore **FAILED**. The cause of the differing layers was not isolated and no base-image or Dockerfile tweaking followed.

Docker Scout `1.18.3` could not produce a CVE report because it requires Docker Hub login. Trivy, Grype, and Syft are not installed. The scan is **BLOCKED**, and SBOM status is **NOT GENERATED**; no assertion about the candidate's vulnerability count is made.
