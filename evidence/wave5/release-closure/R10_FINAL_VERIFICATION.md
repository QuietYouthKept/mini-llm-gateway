# R10 Final Verification Record

As of 2026-10-10. This is an engineering evidence record, not release approval.

## Source identity

- Branch: `codex/wave51-release-closure`
- Iteration 1 code: `4febd225a1e5fc1144cda0f4596a5af16242c2a9`
- Current source: `c9ddbe65f94f460a55cad07fe78c5e6b061f6dc4`
- Current tree: `322a6116f590cdaf55cad07fe78c5e6b061f6dc4`
- Current-source image: none. The diagnostic after leg mounts the current `app/` read-only over the previous candidate image `sha256:44486db8bb69095129d72cb1303937df117d968ffae703b8e3055a021fd5dacf` (built from `5a474c2`).

## Current-source local verification

| Check | Environment / command | Result |
| --- | --- | --- |
| Targeted cancellation-lane regression | `uv run pytest -q tests/unit/test_streaming_failure_semantics.py::test_buffered_chat_cancellation_uses_finalization_lane_for_recovery` | 1 passed |
| Ruff | Python 3.11 locked environment, `uv run ruff check .` | exit 0 |
| Compileall | Python 3.11 locked environment, `uv run python -m compileall -q app tests eval scripts` | exit 0 |
| Full pytest + PG probe | Python 3.11.9; isolated PostgreSQL; `pytest -q --cov=app --cov-branch --cov-precision=2` | 208 passed, 0 skipped; pytest exit 0 |
| Independent pytest-only coverage gate | `coverage report --fail-under=80 --precision=2` using pytest-only data | 83.25%; exit 0 |
| Full local test on Python 3.14 | same suite and PG service | 208 passed; coverage 79%; independent gate exit 2. This discrepancy is retained; gate was not lowered. |
| `git diff --check` | current pre-documentation diff | exit 0 |

Detailed local JUnit/XML/logs and exit codes are in `r10-iteration2-py311-final-*`; the failed Python 3.14 gate and the initial wrong-role PostgreSQL DSN attempt are kept under separate `r10-iteration2-*` artifacts.

## Remote CI and evidence

- [GitHub Actions Run 38028193676](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38028193676), tested SHA `c9ddbe65f94f460a55cad07fe78c5e6b061f6dc4`: Success; 208 passed, 0 skipped; pytest-only branch coverage 83.47%; independent 80% gate passed.
- Ruff, compileall, PostgreSQL integration, Redis adapter, Redis two-replica, HTTP/SSE, Provider Contract, Functional Eval 7/7, Security Eval 8/8, Secret Scan, Dependency Audit and repository hygiene all succeeded.
- Evidence Artifact `11660363882`; Validation Artifact `11660778588`.
- Manifest reports 155 expected/actual files, zero missing/extra/hash/size mismatches; local independent rehash agrees. Manifest SHA-256: `68e139050cc59fae1ce7fffcf1ab51bfe46b86365199874cd711fbbe54ad98ce`.
- Local downloaded artifacts are under `remote-artifacts-r10-run-38028193676/`.

## Matched-resource performance and durable state

The diagnostic uses the same deterministic `mock_fast` stub, seed `20261010`, config SHA-256 `ef096980139cdafc86836cccffb5a66a9059e2949a99b94157af8278359a5bf5`, 10-second warmup + 30-second formal runs, three repetitions at concurrency 1/8/32/64, and Compose limits of gateway 2 CPU/1 GiB, PostgreSQL 2 CPU/1 GiB, Redis 1 CPU/512 MiB.

| Concurrency | Baseline success | After-source success | After-source errors | Mean after RPS | Mean after P95 | Max after P99 |
| ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 1 | 100.00% (840/840) | 100.00% (852/852) | none | 9.39 | 140 ms | 210 ms |
| 8 | 100.00% (2,368/2,368) | 100.00% (3,200/3,200) | none | 35.25 | 286 ms | 331 ms |
| 32 | 80.35% (2,777/3,456) | 71.02% (2,727/3,840) | 1,113 `database_admission_overloaded`; zero `database_unavailable` / `stream_finalization_unknown` | 40.78 | 1,121 ms | 1,599 ms |
| 64 | 28.42% (1,746/6,144) | 80.08% (3,280/4,096) | 816 `database_admission_overloaded`; zero `database_unavailable` / `stream_finalization_unknown` | 40.51 | 3,471 ms | 5,565 ms |

Before any reconciliation, the baseline database had 10,508 settled reservations/receipts/attempts plus 832 expired `reserved` rows without receipts; none were reconciled. The after-source database had 13,507 settled reservations, 13,507 settle receipts, 13,507 provider attempts, 16,455 request logs, zero duplicate request receipts, zero reserved/expired rows, and no reconciliation. At post-load scrape the finalization lane had zero admission rejects; the ordinary DB lane had 3,733. During-source samples (51) observed gateway/PostgreSQL/Redis peak CPU 188.10%/209.52%/5.19% and peak memory 93.33/82.54/12.80 MiB. Baseline resource samples were not collected. The post-load event-loop lag gauge was 0; this is not a during-load measurement.

All individual raw JSON/CSV, warmup/formal logs, and exit codes are under `r10-iter1-baseline/` and `r10-iter1-source/`. Full structured summary: `R10_BEFORE_AFTER_BENCHMARK.json`.

## Build and release gate status

- Current-source clean Docker builds A and B at `4febd22` failed with BuildKit/PyPI TLS EOF (exit 1); no TLS verification was disabled. A later Compose-triggered attempt for the new source was interrupted after the same TLS EOF repeated and produced no candidate. No more blind build retries were made. Current-source R01 is FAILED; R02 is BLOCKED.
- R03 runtime hardening, R04 vulnerability disposition, and R07 rollback have evidence only for earlier exact images/source pairs. R04 remains FAILED with 44 High findings on the previous candidate; no risk exception was approved.
- R05 outage/recovery has six passing 20/50 request oracles for source 5a, but is not a current-source image verification.
- R06 real PostgreSQL COMMIT ACK loss remains NOT EXECUTED; synthetic exception injection is not wire-level evidence.
- R08 OTel/Prometheus end-to-end backend query remains PARTIAL.
- R09 live DNS rebinding/redirect/private/metadata/IPv6/proxy-bypass checks remain PARTIAL.
- R10 remains FAILED. The corrected error taxonomy and durable accounting improved, but bounded admission failures at c32/64, high c64 tails, missing current-source image, and incomplete resource/event-loop baselines prevent acceptance.
- R11 is PASS for source `c9ddbe6` based on the remote CI and validated artifact above.

No completion tag, main merge, registry image push, or production deployment was performed. `RELEASE_READY = FALSE`.
