# mini-llm-gateway

An **explainable, failure-tested LLM Gateway** built with FastAPI and Clean Architecture.
It centralizes model access behind one OpenAI-compatible API and enforces the
governance every AI team ends up hand-rolling: authentication, rate limiting,
token/cost budgets, provider routing, fallback, retry, circuit breaking,
guardrails, request auditing, and Prometheus metrics — plus **explainable routing
decisions**, **failure replay**, and **exact prompt caching**.

Runs entirely locally with mock providers — **no real API keys required** — and
can point at local Ollama/vLLM servers for real-model testing.

[![CI](https://github.com/QuietYouthKept/mini-llm-gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/QuietYouthKept/mini-llm-gateway/actions)

---

## Why this exists

When teams call LLMs directly from business code, every service repeats the same
provider-switching, retry, rate-limit, and budget-tracking logic. A gateway moves
that logic into one place so the rest of the system talks to a single, stable,
auditable API — the same way LiteLLM Proxy, Portkey, and Cloudflare AI Gateway do.

## Architecture

```
                         HTTP clients
                 curl · openai SDK (base_url)

                             |  Bearer <api-key>
                             v
   ┌───────────────────────────────────────────────────────┐
   │  interfaces/http                                       │
   │  /v1/chat · /v1/chat/completions · /v1/requests/{id}  │
   │  /metrics · /admin/*                                   │
   │  auth · request_id middleware · error handlers         │
   └───────────────────────────────┬───────────────────────┘
                                   |
   ┌───────────────────────────────v───────────────────────┐
   │  application (use cases)                               │
   │  ChatService pipeline:                                 │
   │    streaming → rate limit → profile → guardrail        │
   │    → budget → routing → fallback(retry+circuit)        │
   │    → output guardrail → budget commit → audit log      │
   └───────────────┬────────────────────────┬───────────────┘
                   |                        |
   ┌───────────────v───────────┐  ┌─────────v───────────────┐
   │  domain                   │  │  infrastructure          │
   │  ProviderPort (abstract)  │  │  providers: mock /       │
   │  domain models + errors   │  │  openai_compatible       │
   │  ports & use-case DTOs    │  │  sqlite · metrics · yaml │
   └───────────────────────────┘  └─────────────────────────┘
```

The composition root is `app/core/container.py` — one `AppContainer` holds every
wired service, which is what makes `POST /admin/reload-config` a one-liner.

## Features

- **OpenAI-compatible API** — point the official `openai` SDK at this gateway
  (`base_url`) and it works unchanged.
- **API key auth** — clients authenticate at the gateway, not at each provider.
- **Provider routing & fallback** — priority routing with fallback chains that
  degrade gracefully on error / timeout / bad status.
- **Retry + circuit breaker** — exponential backoff on retryable errors, and a
  per-provider closed/open/half-open breaker to stop cascading failures.
- **Rate limiting & token/cost budgets** — atomic reserve/settle/release with a
  strict reservation envelope on SQLite or PostgreSQL (with `Retry-After`).
- **Guardrails** — config-driven input/output policies (blocked regex, length,
  PII & prompt-injection hooks) with audit output.
- **Request auditing** — every call writes `request_logs` + `provider_attempts`;
  `GET /v1/requests/{id}` replays the full attempt chain.
- **Observability** — structured JSON logs, correlated `request_id`, Prometheus
  metrics, and prompt-free OpenTelemetry OTLP traces.
- **Real provider adapter** — `OpenAICompatibleProvider` speaks to any
  OpenAI-style `/chat/completions` endpoint (OpenAI, DeepSeek, Qwen, vLLM…).
- **Config hot reload** — `POST /admin/reload-config` replaces the policy
  snapshot while preserving compatible limiter/cache/breaker/metrics state.
- **Explainable routing** — every response carries a `decision_trace` recording
  *why* a provider was selected, skipped, retried, or fell back.
- **Failure replay** — `scripts/replay_request.py` defaults to deterministic
  offline replay with zero provider calls; live replay is an explicit opt-in.
- **Exact prompt cache** — identical prompts skip the provider call entirely;
  local and Redis backends store only post-guardrail output. Redis deployments
  coalesce a cold miss globally with an owner-safe, TTL-bound lease; outage
  degradation is explicitly local-only.
- **Usage provenance** — provider token usage is settled when available, with
  explicit estimator fallback and separate estimated/actual audit fields.
- **OWASP guardrail attack pack** — a config-driven security eval covering
  prompt injection, system-prompt leakage, PII, and unbounded consumption.
- **Local real-model path** — the same OpenAI-compatible adapter targets Ollama
  or vLLM, so the gateway is not mock-only.

## Quick start

Requires **Python 3.11+**. `uv` is recommended.

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python -e ".[dev]"

# macOS / Linux: .venv/bin/python
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Verify:

```bash
curl http://localhost:8000/health
# {"status":"ok","service":"mini-llm-gateway"}

curl http://localhost:8000/v1/chat \
  -H "Authorization: Bearer demo-key" \
  -H "Content-Type: application/json" \
  -d '{"profile":"fast-chat","messages":[{"role":"user","content":"hi"}]}'
```

Or via Docker:

```bash
docker compose up --build
```

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | Health check |
| POST | `/v1/chat` | Gateway-native chat (verbose governance metadata) |
| POST | `/v1/chat/completions` | OpenAI-compatible chat completions |
| GET | `/v1/requests/{request_id}` | Request audit trail (with attempt chain) |
| GET | `/metrics` | Prometheus metrics |
| GET | `/admin/config` | Redacted config (admin key) |
| POST | `/admin/reload-config` | Hot reload config (admin key) |
| POST | `/admin/reconcile-budget-reservations` | Explicitly reclaim expired crash leases (admin key) |

Auth: `Authorization: Bearer <api-key>` or `x-api-key`. Admin endpoints use
`x-admin-key: admin-key` (default).

## Demo & reports

```bash
make demo                 # 10 failure-injection scenarios, PASS/FAIL
make demo-report          # writes docs/demo-report.md (traces + metrics)
make replay REQUEST_ID=x  # replay a historical request, detect regressions
.venv/Scripts/python scripts/final_demos.py  # 4 concise acceptance demos
```

`make demo-report` renders a markdown report — see
[docs/demo-report.md](docs/demo-report.md) — with the explainable decision trace
for each routing scenario and a metrics snapshot.

## Test & eval

```bash
make test           # pytest (unit + integration)
make lint           # ruff
make eval           # config-driven eval harness (eval/eval_cases.yaml)
make security-eval  # OWASP attack pack (eval/security_cases.yaml)
```

## Configuration

Everything is driven by `config/config.yaml`: clients (rate limit + budget),
providers (mock or `openai_compatible`), model profiles (routing + fallback),
retry, circuit breaker, guardrails, metrics, admin, and observability. To use a
real provider, uncomment and enable the `openai` block and set `OPENAI_API_KEY`.
Request bodies and replay payloads are independently opt-in under `logging`;
both are disabled in the checked-in config.

Runtime backend selection is environment-driven:

| State | Local default | Shared option | Selection |
| --- | --- | --- | --- |
| budget + audit | SQLite | PostgreSQL | `GW_DATABASE_URL=postgresql://...` |
| rate limit | in-process | Redis | `GW_REDIS_URL=redis://...` |
| exact cache + singleflight | in-process | Redis | `GW_CACHE_BACKEND=redis` plus `GW_REDIS_URL` |
| traces | bounded local recorder | OTLP/HTTP | `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://.../v1/traces` |

Install shared-backend dependencies with `uv pip install -e ".[production]"`.
Public dataset tooling additionally uses `.[datasets]`.

## Verification evidence

The 2026-08-23 hardening pass used deterministic WildChat and UltraChat fixtures,
real Uvicorn processes, a local OpenAI-compatible fault provider, disposable
Redis/PostgreSQL/OTel containers, and a fresh copied checkout. See
[the evidence report](docs/production-hardening-report-2026-08-23.md),
[formal test cards](docs/test-cards/public-dataset-production-evidence.md), and
[bounded load results](docs/load-test-results-2026-08-23.md).

## Honest scope notes

- **Local-first defaults**: SQLite budget/audit works across local processes;
  in-process rate limit/cache/breakers do not. Redis rate limit/cache and
  PostgreSQL budget/audit adapters are implemented and runtime-verified, but
  operating backups, HA, TLS, credentials, dashboards, and alerting remains the
  deployer's responsibility.
- **Distributed singleflight is best-effort**: with Redis available, identical
  cache misses are globally coalesced. On Redis outage cache and singleflight
  fail open to local behavior; the shared rate limiter is fail-closed by default.
- **Circuit breakers remain process-local** by design.
- **Hot reload preserves retired resources until shutdown** so in-flight work is
  safe; repeated reloads can temporarily retain extra clients/connections.
- **Offline replay simulates routing decisions** from recorded metadata. It does
  not execute providers unless live replay is explicitly requested.
- **Request audit bodies remain opt-in** and are disabled by default; failed
  provider attempts are available in the authenticated request audit endpoint.
- **Guardrails are heuristics**, not a guarantee against prompt injection or PII
  leakage — they provide configurable policy hooks + audit logs.
- **Streaming** is deliberately rejected in the MVP (`stream: true` → 400); the
  policy is configurable.

## Project structure

```
app/
  domain/          models, ports, errors (no framework deps)
  application/     services + use-case orchestration
  infrastructure/  providers, sqlite, config, observability
  interfaces/http/ routes, schemas, dependencies, middleware
  core/            container (composition root), settings, startup
tests/             unit + integration tests
eval/              eval harness + OWASP security cases
scripts/           demo, demo-report, replay scripts
```

See [docs/architecture.md](docs/architecture.md) and the ADRs under `docs/adr/`
for the reasoning behind key decisions.
