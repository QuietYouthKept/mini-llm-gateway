# Existing Test System Audit

## Identity and method

Audited commit `16f3b527e0b9fe86560b9bc7aaf58031cd27e651` (tree `d6f102af676ad46960b2b68962c73318867862e1`) in the isolated E: worktree. D: contains unrelated, uncommitted user changes and was not used for test execution. Inventory found 32 `test_*.py` files: 24 under `tests/unit`, 7 under `tests/integration`, and one top-level production-hardening test module. A source-pattern inventory found 220 test function definitions; this is a definition count, not an executed count. Execution counts will be filled only from pytest output.

The Gateway lockfile was installed into this worktree's own `.venv` with Python 3.11.9 via `uv sync --frozen --extra dev --extra production --extra datasets`. The separate helper environment passed `pip check` and imports Hypothesis 6.169.0, Schemathesis 4.30.1, and PyArrow 26.0.0. The locked Gateway environment resolves PyArrow 25.0.1; the helper environment remains separate.

## Existing high-value tests and assertions

| Test location | Actual assertion evidence | Transport / persistence | Side effects checked | CI |
|---|---|---|---|---|
| `tests/unit/test_streaming_failure_semantics.py` | Pre-token fallback; no fallback after emitted content; provider metadata isolation; unstarted close; response-start failure; settlement rejection; cancellation; commit-ack-loss recovery; unknown commit is not retried; finalization lane overload; disconnect after settlement; circuit-open and missing-provider behavior | In-process async service; SQLite-backed test container; not real TCP | Request audit, attempts, reservation state, receipt count, false usage prevention | Fast/full pytest |
| `tests/unit/test_streaming_budget.py` | Cancellation settles observed output; timeout produces SSE error and terminal audit | In-process; SQLite | Audit status and reservation final state | Full pytest |
| `tests/integration/test_uvicorn_streaming_e2e.py` | Real Uvicorn TCP: complete SSE and audit; client disconnect cleanup; timeout fallback; late provider error emits `error`, not `done`; late fallback is absent | TCP loopback; fixture-backed SQLite | Request logs, attempt rows, finalization state | Dedicated CI HTTP/SSE step |
| `tests/integration/test_postgres_repository_integration.py` | Repository operations against PostgreSQL when configured | Real PostgreSQL integration probe | Repository/persistence checks as implemented by fixture/probe | Dedicated CI PG probe |
| `tests/integration/test_postgresql_pool_reliability.py` | Pool lifecycle/concurrency/recovery assertions | PostgreSQL-dependent integration | Pool/repository behavior | Full pytest when PG configured |
| `tests/unit/test_openai_compatible_provider_contract.py` and `test_openai_compatible_provider.py` | OpenAI-compatible request/response shape, streaming parse and error contract | Mock HTTP transport | Provider mapping and error classification | Dedicated Provider Contract CI step |
| `tests/unit/test_provider_egress.py` | URL / egress config guards | Unit | No network side effects | Dedicated Provider Contract CI step |
| `tests/unit/test_token_budget_service.py` | Reservation/finalization state, receipt, idempotence, bounded outcomes | In-process; SQLite repository | Reservation and receipt invariants | Full pytest |
| `tests/unit/test_redis_two_replica_probe.py` | Redis multi-replica probe behavior | Probe-level tests; live Redis only when separately configured | Cross-replica behavior | Full pytest |
| `tests/unit/test_rate_limiter.py`, `test_prompt_cache.py`, `test_providers.py`, `test_fallback_service.py`, `test_circuit_breaker.py` | Local service/adapter contract assertions | Primarily in-process/mock; check test code for each case before counting a live test | Decision, cache, rate-limit, attempts as asserted | Full pytest |
| `tests/test_production_hardening.py` | Broad production hardening regressions | Mixed fixture/mock and repository-level behavior | Case-dependent; not one uniform backend | Full pytest |
| `eval/eval_cases.yaml`, `eval/security_cases.yaml`, `eval/run_eval.py` | Deterministic functional and security rule cases | Local eval harness | Evaluator results, not persistence | Dedicated Functional/Security CI steps |
| `scripts/postgres_commit_ack_loss_probe.py`, `scripts/postgres_outage_tcp_probe.py` | Standalone commit-ack-loss and DB outage probes | Real TCP/PG when explicitly run | Probe-specific durable state | Not every probe is a pytest CI step |
| `scripts/fault_provider_app.py` | Existing `/health`; stream success, timeout and malformed-SSE modes; buffered timeout/500 | Local HTTP provider, no TCP cut injection inside the app | No independent cross-check of Provider B counters | Used by selected local experiments |

## Eighteen-category coverage map

Detailed classification is in `01_TEST_COVERAGE_MATRIX.csv`. The matrix distinguishes mock from TCP, SQLite from PostgreSQL, Redis use, persistence checks, side-effect assertions and CI placement. A module's existence does not establish that every scenario is present or executed.

## Gaps confirmed by initial source review

1. The deterministic fault provider now supports bounded status, SSE framing, usage and delayed-reset modes with aggregate `/stats`; ten unit scenarios pass. This remains a fixture, not provider certification.
2. A real TCP test now proves that three nonempty chunks reached the client before an injected reset; it verifies no Provider B request, no `done`, one request audit and settled SQLite reservation. The first stalled experiment's timeout result is preserved separately.
3. Real PostgreSQL probes remain unexecuted in this wave. The full suite skipped PostgreSQL-dependent cases; no PostgreSQL transaction/isolation or distributed-consistency claim is made.
4. The prompt-injection Parquet has 546 training and 116 test rows with columns `text` and `label`; aggregate-only rule evaluation ran over all 662 rows. Provenance/license and label semantics are unknown; no accuracy/model-safety claim is made.
5. No WildChat, UltraChat, Azure LLM 2023, or Agent Security Bench location/license was found under the bounded `E:\04_Datasets_数据集标注` scan. Broader personal-data searches were not performed.
6. Host available RAM remained below the task's 6 GiB threshold. Additional database/container stacks and high-concurrency/load/soak tests remain resource-blocked.
7. Existing release risks remain unchanged: Docker reproducible build FAILED; prior rollback PARTIAL; historical image scan has 44 High findings; HA/secret-manager/alerting gates remain incomplete.

## Wave 6 execution outcome

Final full pytest passed 242 with 6 skips and 81.37% pytest-only branch coverage. Hypothesis ran 15 bounded HTTP examples with persistent assertions on all eight successful requests. Schemathesis generated 127 passing cases across the two Chat operations. The final Toxiproxy run passed one injected-reset scenario. Exact command output and exit codes are indexed in `TEST_EVIDENCE_INDEX.md`. PostgreSQL/Redis, remote CI, load performance and current Docker deployment gates remain open.
