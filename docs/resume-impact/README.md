# mini-llm-gateway — Resume Impact Sprint

This branch turns the existing gateway into a reproducible portfolio demo for backend reliability and LLM infrastructure. It adds request-ID trace correlation, database blocking-I/O spans, a real PostgreSQL COMMIT-ack-loss probe, an isolated observability Compose stack, and an offline deterministic demo. It does **not** claim production release readiness or a performance improvement from this sprint.

## Architecture at a glance

```text
HTTP/SSE client
  └─ RequestContextMiddleware: request ID + route/status span
       └─ ChatService: routing / provider / budget / finalization spans
            └─ BoundedBlockingIO: bounded DB/Redis operation span
                 ├─ PostgreSQL: budget, request audit, attempts, finalization receipt
                 └─ Redis: rate limit, prompt cache, distributed singleflight

Gateway /metrics ──> Prometheus API ──> Grafana dashboard + alerts
Gateway OTLP ──> OpenTelemetry Collector ──> Jaeger v2 query API/UI
```

## Reproduce the local demo

From the sprint worktree, use Python 3.11 and the locked dependencies. Docker Compose uses only loopback-published ports and a unique project/network. The passwords below are synthetic local-only values; do not replace them with production credentials.

```powershell
$env:RI_POSTGRES_PASSWORD = 'local-synthetic-only'
$env:RI_GRAFANA_PASSWORD = 'local-synthetic-only'
docker compose -p resume-impact-sprint -f deploy/resume-impact/compose.yaml up -d
$env:GW_DATABASE_URL = 'postgresql://gateway:local-synthetic-only@127.0.0.1:25432/gateway'
$env:GW_REDIS_URL = 'redis://127.0.0.1:26379/0'
$env:GW_CACHE_BACKEND = 'redis'
$env:GW_CONFIG_PATH = 'config/config.yaml'
$env:OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = 'http://127.0.0.1:24318/v1/traces'
.\.venv\Scripts\python.exe scripts\migrate_postgres.py
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18150
```

The default portfolio demo is fully offline: it creates temporary SQLite state and uses deterministic mock providers.

```powershell
.\.venv\Scripts\python.exe scripts\resume_impact_demo.py
```

To point the same scenarios at the separately running PostgreSQL/Redis-backed local gateway instead:

```powershell
.\.venv\Scripts\python.exe scripts\resume_impact_demo.py --url http://127.0.0.1:18150
```

Then run the optional real-service probes:

```powershell
.\.venv\Scripts\python.exe scripts\postgres_integration_probe.py --database-url $env:GW_DATABASE_URL
.\.venv\Scripts\python.exe scripts\redis_adapter_integration_probe.py --redis-url $env:GW_REDIS_URL
.\.venv\Scripts\python.exe scripts\redis_two_replica_integration_probe.py --database-url $env:GW_DATABASE_URL --redis-url $env:GW_REDIS_URL
```

Open Prometheus at `http://127.0.0.1:29090`, Grafana at `http://127.0.0.1:23000`, and Jaeger at `http://127.0.0.1:26686`. For direct, machine-checkable proof, query `http://127.0.0.1:29090/api/v1/query?query=llm_gateway_requests_total` and Jaeger's v3 trace endpoint with `query.service_name` plus RFC3339 `query.start_time_min` and `query.start_time_max`. Match `request.id` on `http.server.request` to the same trace's `blocking_io.operation` spans (`dependency.name=database` or `redis`).

The `postgres_integration_probe.py` includes a TCP proxy scenario that forwards PostgreSQL protocol responses through `CommandComplete(COMMIT)` and then closes before forwarding `ReadyForQuery`. Expected evidence is a client-side `psycopg.OperationalError`, a directly queryable settled receipt, exactly one audit row, one provider attempt, 12 usage tokens, and an idempotent replay. This tests a real wire-level lost acknowledgement; the older injected post-commit exception remains separately labelled as a simulated failure.

## Verified in this sprint

- PostgreSQL integration probe: cold-start budget reservation, reservation/finalization races, transaction rollback, idempotent replay, orphan lease reclamation, and real TCP COMMIT acknowledgment loss.
- Redis adapter and two-Uvicorn-replica probes: 10/20 shared rate-limit requests admitted, cross-replica cache equality, one provider execution under distributed singleflight, stale lease recovery, and explicit fail-open/fail-closed outage modes.
- Trace backend query and Prometheus target/query were exercised against real local services, not inferred from `/metrics` returning 200.
- `scripts/resume_impact_demo.py` runs synthetic normal, provider-fallback, SSE, audit, and metrics scenarios. Default mode is offline with temporary SQLite and deterministic mocks; optional `--url` mode targets a live gateway. Neither mode makes paid provider calls or emits prompts/completions in its report.

These local probes are not yet a remote CI run. The gateway process in the local observability smoke ran directly from source on Windows; it is not a container image acceptance test. The queried correlation example is request `resume-impact-trace-evidence-003`, with DB finalization and Redis operations in the same trace. See [Evidence and boundaries](RELIABILITY_EVIDENCE.md) and [Resume claims](RESUME_BULLETS.md).

## Remaining production gates

- No new reproducible gateway image was accepted or scanned as part of this sprint; prior Docker and staging findings remain version-bound.
- R06 remains unverified; R08/R09 are only partially verified; the earlier release checklist remains authoritative.
- No claim is made that the historical 44 High scan findings apply to this source or are fixed here.
- The previous source-overlay performance samples (32/64 concurrency) are historical evidence, not a before/after performance result for this sprint.
- `RELEASE_READY` remains false unless all pre-existing R01–R11 release gates are independently satisfied.

## Document map

- [Baseline and decisions](00_BASELINE_AND_DECISIONS.md)
- [Evidence and boundaries](RELIABILITY_EVIDENCE.md)
- [Resume claims](RESUME_BULLETS.md)
