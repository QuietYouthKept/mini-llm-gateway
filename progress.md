# Progress Log

## 2026-08-15 — highlight layer (v0.2/v0.3/v0.4)

### Done

- Explainable routing: every /v1/chat response and audit record now carries a
  decision_trace (why a provider was selected / skipped / retried / fell back).
- Failure replay: scripts/replay_request.py re-runs a historical request against
  the current config and reports routing/fallback regressions (make replay).
- One-click demo report: scripts/demo_report.py renders docs/demo-report.md with
  12 scenarios, decision traces, and a metrics snapshot (make demo-report).
- Exact prompt cache: in-memory TTL+LRU cache; cache hits skip the provider and
  budget, with cache_hits/misses and estimated cost-saved metrics + audit fields.
- OWASP guardrail attack pack: eval/security_cases.yaml (8 cases) covering prompt
  injection, system-prompt leakage, SQL injection, PII, unbounded consumption,
  and sensitive-output blocking (make security-eval).
- Local real-model path: config.yaml documents ollama-local and vllm-local
  openai_compatible providers (no cloud key required).
- Schema v3 with idempotent column migrations (decision_trace, replay_payload,
  cache fields) so existing DBs upgrade cleanly.
- Tests: 82 passed; ruff clean; ADR-0004 for the exact-cache decision.

### Next (optional)

- Semantic cache (embedding-based) behind the same interface.
- Redis-backed cache + rate limiter for multi-replica deployments.
- Streaming (SSE) support.
- OpenTelemetry traces with GenAI semantic attributes.

---

## 2026-08-14 — production-oriented build-out

### Done

- Fixed the toolchain: Python 3.11 venv (uv), pytest runs async tests for real
  (71 passed), ruff clean, GitHub Actions CI.
- Completed the gateway data plane end to end: /v1/chat, /v1/chat/completions,
  /v1/requests/{id}, auth, rate limiting, token/cost budgets, routing, fallback,
  retry, circuit breaker, guardrails, audit logging, structured JSON logs,
  request_id propagation, Prometheus /metrics.
- Real OpenAI-compatible provider adapter; config hot reload; demo + eval harness;
  README + architecture doc + ADRs 0001-0003.
