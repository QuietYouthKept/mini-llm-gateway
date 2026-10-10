# Reliability and Observability Evidence

Date: 2026-10-10. Branch: `codex/resume-impact-sprint`. Base: `ecae81222810ac2ac7b85823b56f473cc7637644`.

All raw sprint command outputs are stored outside the repository in `E:\mini-llm-gateway-resume-impact-evidence\`; synthetic credentials were supplied only through process environment variables. The files are local operator evidence and are not committed.

## Actual local results

| Probe | Result | What the oracle checked |
| --- | --- | --- |
| `scripts/postgres_integration_probe.py --database-url ...` | PASS, exit 0 | Concurrent budget reservation; atomic/idempotent settlement; commit-unknown recovery; rollback; expired reservation reconciliation; unique request/attempt rows |
| TCP COMMIT acknowledgment loss | PASS, exit 0 | Proxy observed `CommandComplete(COMMIT)`, dropped subsequent ReadyForQuery, client got `psycopg.OperationalError`; receipt recovered as `settled`; replay applied no second charge; exactly one audit and one attempt; usage exactly 12 tokens |
| `scripts/redis_adapter_integration_probe.py --redis-url ...` | PASS, exit 0 | 10 admitted / 10 rejected under global rate limit, exact shared cache, singleflight lease expiration/stale-owner checks, explicit fail-open/fail-closed outage modes |
| `scripts/redis_two_replica_integration_probe.py --database-url ... --redis-url ...` | PASS, exit 0 | Two real Uvicorn processes; cross-replica cache equivalence; one provider execution; rate-limit consistency; shared PostgreSQL budget race with one 200 and one 429; settled reservation and one provider attempt |
| Local HTTP readiness / smoke | PASS after recovery interval | Initial `/ready` correctly returned 503 `recovering`; subsequent readiness returned 200 after DB, Redis and provider probes succeeded. `/metrics` returned 200. Synthetic Chat returned 200 through PostgreSQL and Redis.
| Prometheus | PASS | Scrape target `mini-llm-gateway` reported `health=up`; API query returned `status=success`. The actual metric name is `llm_gateway_requests_total`.
| OTel Collector → Jaeger v2 | PASS after config correction | Jaeger `/api/v3/services` listed `mini-llm-gateway`; actual chat trace `9ad62404561df7b320b5ad0198805c5b` contained request ID `resume-impact-trace-evidence-003`, DB finalization and Redis spans under the same trace ID.
| Alert/Grafana query surfaces | PASS, no alert fired | Both Prometheus alert rules loaded with health `ok` and state `inactive`; Grafana `/api/health` reported database `ok`. This does not prove a deliberate alert firing or page delivery.
| Targeted Ruff and pytest | PASS, 35 passed | Changed observability code and tests passed targeted validation.
| Offline portfolio demo | PASS | Three deterministic scenarios completed against temporary SQLite and mock providers; report omits prompt/completion bodies.

## Coverage and final source gates

- Final full pytest: **210 passed**, no skipped tests; combined coverage report **84.19%**. Coverage XML reports **86.96% line rate** and **71.40% branch rate**. The independent project gate `coverage report --fail-under=80 --precision=2` exited 0. These are different measures; do not call the 84.19% total the branch rate.
- Focused real PostgreSQL integration probe coverage: **58% combined** (`connection.py` 51%, `repositories.py` 64%).
- Focused real Redis adapter probe coverage: **88% combined** (`prompt_cache.py` 88%, `rate_limiter.py` 91%, `singleflight.py` 85%).
- Ruff, `compileall`, Functional Eval (**7/7**), Security Eval (**8/8**), Provider Contract (**13 passed**), TCP SSE E2E (**2 passed**), Secret Scan, and `git diff --check` exited 0.
- `pip-audit==2.9.0` audited the sprint venv via `uv tool run`; it found no known vulnerabilities in the installed Python packages. This is not an OCI image scan.

The Commit-Unknown probe is reproducible via `scripts/postgres_integration_probe.py`, which invokes `scripts/postgres_commit_ack_loss_probe.py`. The probe does not simply throw an application exception: it relays the actual database protocol, forwards the `COMMIT` command completion, and drops the next protocol acknowledgment to force the driver into an ambiguous result.

## Controlled environment and failures encountered

- The compose stack is isolated as `resume-impact-sprint` and binds only loopback ports: PostgreSQL 25432, Redis 26379, Jaeger 26686, Collector 24318, Prometheus 29090, Grafana 23000. Host port 15432 was already unavailable and was not disturbed.
- Docker Hub / mirror pulls for Jaeger failed with TLS EOF. Instead of presenting a pull as successful, the official Jaeger 2.22.0 Linux binary was downloaded from the official GitHub release and its SHA-256 verified (`cb0c0be9a4b8fba424bbbc6217b0feb0adeea3bca5b73a83db1af31bb7d34389`) before a local scratch image was built. Image ID: `sha256:98098b4572f5f94af8dc8105d55b5f620671235dc892cd95bd7924c089056afb`. This is an observability demo artifact, not the gateway image and not a production scan result.
- Jaeger v2's bundled OTLP receiver initially listened on container loopback. The Collector log showed connection refused; the configuration was then updated to bind OTLP gRPC/HTTP on the isolated container interface. The later real trace query passed.
- On the first gateway readiness call, dependencies were in `recovering` and readiness returned 503; it returned 200 on subsequent probe cycles. Do not turn the first 503 into a failure claim about dependency availability or hide the observed recovery transition.

## Performance boundary

No benchmark was run in this sprint that can validly establish a performance delta: the local gateway ran directly from source without matched container CPU/memory limits, while the historical comparison used a source overlay with deterministic mock providers and controlled resource limits. Historical R10 data remains useful context but is not a sprint result: c32 success rate 80.35%→71.02% (1,113 after-source admission rejects); c64 28.42%→80.08% (816 rejects; max P99 5,565ms). Those results do not authorize claiming that this sprint improved throughput or p99.

## Remaining risks

- PostgreSQL repositories still establish a synchronous connection per call. This source-level connection churn is real, but this sprint did not isolate it as the dominant performance bottleneck; no pool or worker-count change is claimed.
- PostgreSQL local probe uses a disposable isolated container. It does not prove managed database behavior under production networking, failover, or TLS termination.
- Jaeger default storage is transient in-memory. Traces disappear when the demo container is replaced.
- The local gateway smoke was not a source Docker build, image scan, staging rollback, or remote CI run.
- Docker/staging historical issues and the R01–R11 gate status remain unchanged.

## Raw evidence index

Key local evidence paths:

- `E:\mini-llm-gateway-resume-impact-evidence\postgres-probe-final.log`
- `E:\mini-llm-gateway-resume-impact-evidence\postgres-commit-ack-loss.log`
- `E:\mini-llm-gateway-resume-impact-evidence\redis-adapter-probe.log`
- `E:\mini-llm-gateway-resume-impact-evidence\redis-two-replica-probe.log`
- `E:\mini-llm-gateway-resume-impact-evidence\compose-up-final.log`
- `E:\mini-llm-gateway-resume-impact-evidence\trace-stack-reconfigure.log`
- `E:\mini-llm-gateway-resume-impact-evidence\observability-query-evidence.json`
- `E:\mini-llm-gateway-resume-impact-evidence\observability-components-evidence.json`
- `E:\mini-llm-gateway-resume-impact-evidence\closure-pytest.log`
- `E:\mini-llm-gateway-resume-impact-evidence\release-pytest.log`
- `E:\mini-llm-gateway-resume-impact-evidence\release-coverage.xml`
- `E:\mini-llm-gateway-resume-impact-evidence\release-coverage-gate.log`
- `E:\mini-llm-gateway-resume-impact-evidence\release-functional-eval.log`
- `E:\mini-llm-gateway-resume-impact-evidence\release-security-eval.log`
- `E:\mini-llm-gateway-resume-impact-evidence\postgres-focused-coverage.log`
- `E:\mini-llm-gateway-resume-impact-evidence\redis-focused-coverage.log`
- `E:\mini-llm-gateway-resume-impact-evidence\final-dependency-audit.json`
- `E:\mini-llm-gateway-resume-impact-evidence\closure-secret-scan.log`
- `E:\mini-llm-gateway-resume-impact-evidence\observability-targeted-pytest.log`
