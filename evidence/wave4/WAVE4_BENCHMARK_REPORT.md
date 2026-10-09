# Wave 4 Benchmark Report

## Status: PARTIAL — exploratory synthetic smoke only

Environment: Windows 11 x64, Python 3.11.9, Docker 28.3.3, isolated Gateway + PostgreSQL 16 + Redis 7 Compose project; synthetic `fast-chat` Mock Provider, synthetic `demo-key`, no paid provider or public dataset. Gateway used a local image from a dirty tree. No CPU/memory resource limit was applied, so results are not capacity guarantees.

The existing `scripts/load_test.py` ran once for 10 requests at each concurrency 1, 8, 32 and 64. Each corrected run returned 10/10 HTTP 200 with zero HTTP errors:

| Concurrency | Requests | RPS | P50 ms | P95 ms | P99 ms |
|---:|---:|---:|---:|---:|---:|
| 1 | 10 | 12.64 | 75.62 | 112.12 | 112.12 |
| 8 | 10 | 97.57 | 63.61 | 97.00 | 97.00 |
| 32 | 10 | 78.46 | 73.04 | 124.46 | 124.46 |
| 64 | 10 | 101.01 | 64.99 | 80.57 | 80.57 |

Raw outputs: `benchmark-corrected-concurrency-{1,8,32,64}.json`. These are tiny one-shot samples without warmup or repeat trials, and use one short-prompt workload. An initial attempt used an incorrect URL and got 10 HTTP 404s; those raw records remain as `benchmark-concurrency-1.*` and are excluded from the table. No statistically defensible P95/P99, capacity, cache, fallback, streaming TTFT, resource, or real-model throughput claim follows. No real dataset was selected. No provider spend occurred.

Next benchmark should add warmup and >=3 repetitions, separate workload classes, duration/request caps, CPU/RSS/PG connections/Redis telemetry, per-instance metrics, and Gateway-vs-provider latency decomposition. Real-provider work remains N/A unless explicitly authorized.
