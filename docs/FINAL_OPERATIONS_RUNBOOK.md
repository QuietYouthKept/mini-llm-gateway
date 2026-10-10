# Final Operations Runbook

Commands are examples for a local checkout at `E:\mini-llm-gateway-wave51`; replace the path when cloning elsewhere. Use synthetic credentials only. The user's local proxy port is environment-specific and intentionally is not a project default.

## Local development

```powershell
cd 'E:\mini-llm-gateway-wave51'
uv sync --frozen --extra dev --extra production
Copy-Item config/config.example.yaml config/config.yaml
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The committed development config uses local SQLite/memory defaults. Do not point it at production data. `GET /live` checks process liveness; `GET /ready` checks required dependencies; `GET /metrics` exposes Prometheus text.

## Isolated Docker Compose staging

```powershell
$env:WAVE5_COMPOSE_PROJECT = 'gateway-local-staging'
$env:WAVE5_BIND_PORT = '18150'
$env:GATEWAY_IMAGE = 'mini-llm-gateway:<reviewed-tag-or-digest>'
docker compose -p $env:WAVE5_COMPOSE_PROJECT -f deploy/wave5/compose.yaml up -d --no-build
docker compose -p $env:WAVE5_COMPOSE_PROJECT -f deploy/wave5/compose.yaml ps
Invoke-RestMethod http://127.0.0.1:18150/live
Invoke-RestMethod http://127.0.0.1:18150/ready
```

This Compose file creates an isolated PostgreSQL 16 + Redis 7 network and runs the gateway as UID 10001 with read-only rootfs. It contains synthetic local credentials in the Compose definition; do not reuse them outside staging. Run a separately scoped one-shot migration when automatic migration is disabled. The migration command reads `GW_DATABASE_URL` from the environment:

```powershell
$env:GW_DATABASE_URL = 'postgresql://gateway:<local-password>@127.0.0.1:5432/gateway'
.\.venv\Scripts\python.exe scripts/migrate_postgres.py
```

Do not put real values in shell history or tracked files. The exact container endpoint/port depends on the Compose project; inspect `docker compose ps` before using a host URL.

## Test and evaluation

```powershell
.\.venv\Scripts\ruff.exe check app tests
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe eval/run_eval.py
.\.venv\Scripts\python.exe eval/run_eval.py --cases eval/security_cases.yaml
.\.venv\Scripts\python.exe scripts/secret_scan.py
```

For pytest-only coverage, run pytest with `--cov=app --cov-branch` and then enforce it independently with `coverage report --fail-under=80`. PostgreSQL probe: `python scripts/postgres_integration_probe.py --database-url "$env:GW_DATABASE_URL"`. Redis adapter probe: `python scripts/redis_adapter_integration_probe.py --redis-url "$env:GW_REDIS_URL"`. Redis multi-replica probe: `python scripts/redis_two_replica_integration_probe.py --database-url "$env:GW_DATABASE_URL" --redis-url "$env:GW_REDIS_URL"`.

## Reproducible performance runs

Use the checked-in harness, deterministic mock provider, a unique run ID, and a dedicated database/Redis project. `scripts/run_experiment.py` supports request-count or `--duration-seconds` runs, `--warmup-requests`, `--concurrency`, `--shape`, `--seed`, `--stream`, and `--disconnect-after-chunks`. It writes an immutable per-run folder under `evidence/load/` unless `--output-root` is supplied.

Example single cell:

```powershell
.\.venv\Scripts\python.exe scripts/run_experiment.py --url http://127.0.0.1:18150 --api-key <synthetic-client-key> --profile fast-chat --provider-mode stub --provider-name mock_fast --provider-model deterministic --config config/config.yaml --output-root evidence/load --run-id local-c32-r1 --duration-seconds 30 --warmup-requests 10 --concurrency 32 --shape constant --seed 20261010
```

For a formal comparison, record both source/image identity and exact CPU/memory limits for gateway, PostgreSQL, and Redis; use a fresh isolated database per baseline/candidate; repeat each 1/8/32/64 concurrency cell three times; run 10 seconds warmup and 30 seconds formal as separate duration-based invocations. Inspect reservation/receipt/audit state before running reconciliation.

## PostgreSQL outage and recovery

In a disposable project only, `scripts/postgres_outage_tcp_probe.py --concurrencies 20 50 --repetitions 3 --output <new-evidence-path>` sends real TCP requests while PostgreSQL is killed/restarted. It controls its own Compose project via environment; read `--help` and set `WAVE5_COMPOSE_PROJECT`, `WAVE5_BASE_URL`, and `GATEWAY_IMAGE` to unique local values. The expected service contract is `/live=200`, `/ready=503` during outage, bounded explicit request failures, then readiness recovery. Never kill a shared or production database.

High `llm_gateway_blocking_io_admission_rejects_total` means local lane pressure; it is not proof that PostgreSQL itself is unavailable. Inspect `llm_gateway_blocking_io_active_workers`, `queued_operations`, admission wait, operation execution totals/counts/max, `/ready`, and DB health together. `database_admission_overloaded` is a bounded-capacity rejection; `database_unavailable` means the database dependency is unhealthy/circuit-open; `stream_finalization_unknown` means a submitted transaction's durable result could not be resolved. Do not manually release uncertain reservations.

## Reconciliation, shutdown, and rollback

Use the authenticated admin reconciliation endpoint only after checking the exact database and reservation rows. Reconciliation releases expired orphan reservations with audit/receipt evidence; it does not fix a live saturation problem or erase a failed load result. Preserve a database snapshot before any manual production action.

For graceful shutdown, send SIGTERM through the deployment runtime and allow Uvicorn lifespan shutdown to stop the container and drain bounded worker lanes. Do not force-kill PostgreSQL worker threads; a running synchronous transaction must drain before cancellation is reported.

Upgrade/rollback must use two identified immutable image digests, the same disposable database/Redis state, and readiness + Chat + SSE checks at old/new/old stages. Record migrations and receipt/reservation/audit counts after each phase. The prior `c4ba57d → 5a474c2 → c4ba57d` drill passed for that pair only; the current R10 source does not yet have a built image for a new rollback drill.
