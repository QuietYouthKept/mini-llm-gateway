# R10 Root Cause and Fix Record

Date: 2026-10-10. Iteration 1 source commit: `4febd225a1e5fc1144cda0f4596a5af16242c2a9`; iteration 2 source commit: `c9ddbe65f94f460a55cad07fe78c5e6b061f6dc4`; current tree: `322a6116f590cdaf55cad07fe78c5e6b061f6dc4`.

## Evidence-backed diagnosis

The previous valid mock HTTP load showed admission-reject counter `5,556`, `database_unavailable` responses (240 at c32; 3,234 at c64), `stream_finalization_unknown` responses (105 at c32; 335 at c64), and 614 expired reservations later released by explicit reconciliation. That database was not stopped during the normal-load test. CPU peaked at 187.54% and RSS at 91.19 MiB; no resource quotas were configured. The observation therefore did not establish a PostgreSQL outage.

Source inspection confirmed two reliability-classification defects:

1. `ChatService._is_database_unavailable` treated every `BlockingIOOverloadedError` as PostgreSQL unavailable. A local semaphore timeout could therefore be counted as a database outage.
2. `_submit_finalization` caught any exception and performed receipt lookup. `BoundedBlockingIO` can reject during admission before calling `run_in_executor`; this is known-not-submitted, not Commit Unknown. If that follow-up query was also rejected, the request was mislabeled `stream_finalization_unknown` despite having no finalization transaction submitted.

This confirms a local capacity/error-classification contribution. It does not prove that it was the only cause of the old workload errors; connection churn, PostgreSQL service time, and transaction contention still need the matched-resource measurements.

## Iteration 1 change

- Preserve eight total worker threads. Allocate three to regular PostgreSQL work, three to `database_finalization`, one to Redis, and one default worker.
- Give the finalization lane a bounded maximum of 64 in-flight operations; regular database is capped at 8. Aggregate configured in-flight capacity is 80; no queue is unbounded.
- Route atomic settlement/finalization, release recovery, and receipt lookup through the separate finalization lane. Dependency circuit health remains keyed to `database`.
- Add `database_admission_overloaded` (HTTP 503) for local queue rejection. Actual connection errors and dependency circuit-open remain `database_unavailable`.
- Do not query a receipt after a `BlockingIOOverloadedError` that occurred before submission. `DependencyCircuitOpenError` is handled separately as database unavailability.
- Add low-cardinality per-lane/per-operation execution seconds total/count/max diagnostics.

## Iteration 2 change

Commit `c9ddbe65f94f460a55cad07fe78c5e6b061f6dc4` routes buffered-chat cancellation receipt recovery, cancellation release, and generic-exception release through the bounded `database_finalization` lane as well. `test_buffered_chat_cancellation_uses_finalization_lane_for_recovery` cancels after reservation, asserts those lane choices, then checks the SQLite reservation is `released` and exactly one error audit exists.

## Regression and CI

Local Python 3.11.9 with isolated PostgreSQL: Ruff exit 0; compileall exit 0; pytest 208 passed, 0 skipped; pytest-only branch coverage 83.25%; independent `coverage report --fail-under=80 --precision=2` exit 0. Python 3.14 also ran 208 tests successfully, but its measured branch coverage was 79% and the independent gate exited 2. The CI-matching Python 3.11 result is the local pass. New tests verify finalization can run while regular DB work is saturated, cancellation recovery/release selects the protected lane, and pre-submission overload is not misclassified or receipt-probed.

Remote: [GitHub Actions Run 38028193676](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38028193676), commit `c9ddbe6`: 208 passed; branch coverage 83.47%; independent coverage gate and all PG/Redis/two-replica/HTTP-SSE/provider/eval/security/dependency/secret/hygiene steps succeeded. Evidence/Validation artifacts `11660363882` / `11660778588`; validator and independent local rehash report 155 files, no discrepancy; manifest SHA-256 `68e139050cc59fae1ce7fffcf1ab51bfe46b86365199874cd711fbbe54ad98ce`.

## R10 result

The completed same-resource before/after comparison is in `R10_BEFORE_AFTER_BENCHMARK.json`; raw runs are under `r10-iter1-baseline/` and `r10-iter1-source/`. At c32, baseline success was 80.35% with 500 `database_unavailable` and 179 `stream_finalization_unknown`; after source it was 71.02% with 1,113 explicit `database_admission_overloaded` responses and none of those two dependency/unknown errors. At c64, baseline success was 28.42% (3,960 unavailable + 438 unknown); after source it was 80.08% (816 bounded admission rejections, zero unavailable/unknown). The accounting ambiguity improved materially, but c32 rejection remains substantial and c64 max P99 is 5,565 ms. This is an HTTP Chat diagnostic using a read-only `app/` bind mount on the previous dependency image, not a current-source image test.

Before reconciliation, baseline PostgreSQL held 832 expired `reserved` rows without finalization; no reconciliation was run. The source-leg PostgreSQL held 13,507 settled reservations, 13,507 settle receipts, 13,507 provider attempts, zero reserved/expired rows and zero duplicate request receipts; no reconciliation was run. Finalization-lane rejects were zero, while ordinary database-lane rejects were 3,733 at the post-load scrape. Current-source image build remains unavailable after repeated BuildKit/PyPI TLS EOF; no TLS bypass was attempted. **R10 remains FAILED** because c32 overload is material, c64 tail latency is high, no current-source image exists, and baseline resource/during-load event-loop measurements are incomplete. No further speculative worker-count or network retries are part of this closure.
