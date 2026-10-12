# Wave 6 Test Execution Plan

## Current identity and guardrails

- Source commit: `16f3b527e0b9fe86560b9bc7aaf58031cd27e651`
- Source tree: `d6f102af676ad46960b2b68962c73318867862e1`
- Branch: `codex/gateway-fault-contract-benchmark`
- Worktree: `E:\mini-llm-gateway-fault-testing`
- Evidence root: `E:\project-test-assets\01-gateway\results\wave6-fault-contract-20261012T030137Z`
- Gateway environment: isolated `.venv` in this worktree, synced from `uv.lock` with dev, production, and datasets extras.
- Resource gate: Windows reported 32.7 GiB total and 4.9 GiB available at preflight; do not start additional Docker stacks or heavy load/soak suites while available RAM is below 6 GiB.
- E: free space: 47,048,732,672 bytes at preflight. Evidence budget: 8 GiB maximum; generated test fixtures target <=1 GiB.
- D: worktree has user changes and historical evidence. It is out of scope and must remain untouched.
- Existing Docker containers include multiple Gateway and StrategyOps services. Do not stop, reconfigure, prune, or attach mutating probes to them.

## Queue semantics

`PASS` means the named command actually ran and its assertions passed. A test definition or generated scenario is not an executed scenario. Counts of cases, distinct scenarios, repetitions, and HTTP requests are tracked separately. `BLOCKED_RESOURCE` is not a test failure and must not be presented as a pass.

| ID | Category | Priority | Dependencies | Scope / current status | Actual command | Dataset | Executed cases | Exit | Evidence | Limitation / next action |
|---|---|---:|---|---|---|---|---:|---:|---|---|
| W6-00 | Preflight / environment | P0 | none | PASS: D/E worktrees, remote identity, prepared assets, memory, disk, containers inspected | See `reports/preflight.txt`; `uv sync --frozen --extra dev --extra production --extra datasets` | None | n/a | 0 | `reports/uv-sync.log`, `reports/uv-sync.exitcode` | RAM <6 GiB; no additional container matrix |
| W6-01 | Unit, integration, API, regression, CI audit | P0 | W6-00 | PASS: 32 original modules audited; final full pytest 242 passed / 6 skipped | `uv run pytest -q --cov=app --cov-branch ...` | Repository fixtures | 248 outcomes | 0 | `coverage/pytest-final.*`, `01_EXISTING_TEST_AUDIT.md`, `01_TEST_COVERAGE_MATRIX.csv` | PG-dependent cases skipped; opt-in Toxiproxy separately passed |
| W6-02 | Deterministic Provider / TCP fault platform | P0 | W6-01 | PASS: deterministic controls and 10 unit scenarios added | `uv run pytest tests/unit/test_fault_provider_scenarios.py` | Synthetic only | 10 passed | 0 | `fault-provider/unit-final.log` | Fixture does not certify real provider implementations |
| W6-03 | Post-token stream failure | P0 | W6-02 | PASS: 3 client chunks, injected reset, error event, no fallback; SQLite state checked | `uv run pytest tests/integration/test_toxiproxy_stream_reset_e2e.py` | Synthetic provider, isolated SQLite | 1 final rerun | 0 | `fault-provider/toxiproxy-final.*`, `fault-provider/post-token-three-chunk-reset-*.json` | PG persistence and repeated seeds not tested |
| W6-04 | Routing / fallback / retry / 429 / breaker | P0 | W6-01 | PARTIAL: 52 focused tests passed; no exhaustive 429/retry matrix | Focused pytest suite | Synthetic and existing fixtures | 52 passed | 0 | `reports/reliability-focused.*`, report 03 | Concurrent breaker and all retry budgets remain untested |
| W6-05 | Token accounting / database invariants | P0 | W6-01 | PARTIAL: SQLite atomic/idempotency and recovery assertions; PG not configured | Full pytest + Hypothesis + TCP scenario | Synthetic | 8 valid requests with durable-state assertions plus suite | 0 | `reports/hypothesis-api-result.json`, report 04 | No PG locking/isolation/multi-instance conclusions |
| W6-06 | Public dataset discovery / corpus preparation | P1 | W6-00 | PARTIAL: aggregate-only rule evaluation on 662 rows; provenance/license/label meaning unverified | PyArrow and local guardrail evaluator | Local prompt-injection parquet | 662 rows | 0 | `dataset/prompt-injection-guardrail-aggregate.json` | Not an accuracy or model-safety metric |
| W6-07 | Hypothesis / Schemathesis / API contracts | P1 | W6-01 | PASS bounded: 15 HTTP examples; 127 generated Chat contract cases passed | Hypothesis probe; Schemathesis seed 20261012 | Synthetic | 15 + 127 | 0 | `reports/hypothesis-api-*`, `reports/schemathesis-final.*` | Two operations and bounded generation only |
| W6-08 | Metrics and benchmark collection | P1 | W6-01 | PARTIAL: scenario metrics measured; performance telemetry not collected | See `06_GATEWAY_METRICS_DEFINITION.md` | Synthetic | bounded scenario metrics | n/a | `06_GATEWAY_METRICS_RESULTS.csv` | RPS, latency, CPU/RSS not measured |
| W6-09 | Streaming load / stress / spike / soak | P1 | W6-03,W6-05,W6-08 | BLOCKED_RESOURCE | Not run | Synthetic | 0 | n/a | `performance/` | Available RAM <6 GiB; retry only after resources recover and isolated stack budget is available |
| W6-10 | ASVS / prompt injection security | P1 | W6-00 | PARTIAL: Security Eval 8/8; aggregate rule evaluation on 662 rows | Repository security eval + dataset evaluator | ASVS-oriented; local parquet | 8 + 662 rows | 0 | `reports/security-eval.*`, dataset aggregate, report 08 | Not ASVS compliance; provenance/license/labels unknown |
| W6-11 | Deployment / recovery / observability audit | P1 | W6-01 | PARTIAL with historical failures preserved | Wave5 evidence review | Historical Wave5 evidence | 0 new deployment tests | n/a | `09_DEPLOYMENT_RECOVERY_OBSERVABILITY_MATRIX.md` | Docker reproducibility FAILED; 44 High findings open; rc1 rollback PARTIAL |
| W6-12 | CI layering / artifact evidence | P1 | W6-01 | NOT RUN remotely | No push or Actions run in this execution | N/A | 0 | n/a | `ci/` | Local evidence is not a GitHub Actions artifact |
| W6-13 | Quantified resume results | P1 | W6-03..W6-12 | PASS bounded claims only | Derived from raw evidence | Actual evidence only | n/a | n/a | `10_RESUME_READY_QUANTIFIED_RESULTS.md` | No production capacity claim |
| W6-14 | Interview deep dive | P2 | W6-13 | PASS bounded explanation | Source/test/evidence review | Actual source/evidence | n/a | n/a | `11_INTERVIEW_DEEP_DIVE.md` | State persistence and deployment limits explicitly |
| W6-15 | Final acceptance / evidence manifest | P0 | all feasible tasks | PARTIAL: local acceptance documented | Final local gates | All feasible local evidence | See acceptance report | n/a | `12_FINAL_TEST_ACCEPTANCE.md`, `TEST_EVIDENCE_INDEX.md` | Remote CI, PG/Redis, performance and deployment gates remain open |

## Current stop conditions

1. Do not start an additional Docker stack, 20+ concurrent load, stress, or soak while available host memory is below 6 GiB.
2. Do not use an existing database container for destructive or stateful probes unless it is proven to be a disposable, isolated database created for this execution.
3. Do not use WildChat, UltraChat, Azure LLM, or Agent Security Bench until the actual file version, schema, license, and privacy handling are verified.
4. Do not publish raw prompts or secrets. Evidence is external to Git by default.
5. Do not report a Release Ready state; known production gates remain open.

## Final status update (2026-10-12)

Bounded local work is complete for this execution. Final full pytest passed 242 with 6 skips and 81.37% pytest-only branch coverage; independent 80% coverage gate exit was 0. The final opt-in Toxiproxy reset test passed. Remote CI, PostgreSQL/Redis integrations, performance/load suites and current-image deployment/security gates remain incomplete. See `12_FINAL_TEST_ACCEPTANCE.md`.
