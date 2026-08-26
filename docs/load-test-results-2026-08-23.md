# Bounded process load evidence — 2026-08-23

This is a workstation smoke/load matrix, not a production capacity benchmark.
It used one real Uvicorn gateway process, a deterministic local
OpenAI-compatible provider, SQLite state, and HTTP over loopback. No paid API
was called.

## Environment

- OS: Windows 11 Home China, build 10.0.26200
- CPU: AMD Ryzen 9 7845HX, 12 cores / 24 logical processors
- RAM: 33,518,596,096 bytes (about 31.2 GiB)
- Python: CPython 3.11.9
- Gateway process PID during the matrix: 46128
- Evidence files: `E:\project-test-assets\01-gateway\results\load-*.json`

## Results

| Scenario | Requests / concurrency | RPS | p50 / p95 / p99 ms | Attempts/request | Cache hit | Fallback | Retry amp. | HTTP errors | CPU s / RSS delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| constant | 40 / 8 | 22.02 | 345.73 / 416.61 / 424.60 | 1.000 | 0.000 | 0.000 | 0.000 | 0 | 0.547 / +2,289,664 B |
| ramp | 30 / 8 | 22.26 | 344.50 / 359.01 / 401.17 | 1.000 | 0.000 | 0.000 | 0.000 | 0 | 0.344 / +561,152 B |
| spike | 40 / 32 | 21.14 | 1109.27 / 1495.94 / 1515.74 | 1.000 | 0.000 | 0.000 | 0.000 | 0 | 0.500 / +3,321,856 B |
| cache-heavy | 60 / 12 | 61.91 | 169.79 / 256.36 / 306.05 | 0.067 | 0.933 | 0.000 | 0.000 | 0 | 0.312 / +929,792 B |
| cache-miss | 40 / 12 | 22.71 | 506.10 / 571.59 / 573.19 | 1.000 | 0.000 | 0.000 | 0.000 | 0 | 0.453 / +704,512 B |
| long-context | 20 / 4 | 11.39 | 322.98 / 436.75 / 502.66 | 0.200 | 0.800 | 0.000 | 0.000 | 0 | 1.453 / 0 B |
| provider-latency | 30 / 8 | 21.34 | 353.16 / 398.18 / 402.14 | 1.000 | 0.000 | 0.000 | 0.000 | 0 | 0.344 / +8,192 B |
| provider-timeout | 20 / 4 | 17.96 | 176.19 / 402.81 / 408.97 | 2.200 | 0.000 | 1.000 | 0.200 | 0 | 0.250 / -12,288 B |
| retry-storm | 20 / 4 | 16.44 | 231.36 / 296.62 / 302.23 | 2.200 | 0.000 | 1.000 | 0.200 | 0 | 0.281 / 0 B |
| soak | 80 / 8 | 22.21 | 355.03 / 403.24 / 409.18 | 1.000 | 0.000 | 0.000 | 0.000 | 0 | 0.922 / +450,560 B |

All scenarios had zero unexpected HTTP errors and zero classified SQLite,
PostgreSQL, or Redis backend errors in the load-tool output. Budget/rate-limit
reject counts were zero because this matrix measured successful and expected
fallback workloads; boundary rejection is covered separately by the public-data
experiment and Redis/PostgreSQL cards.

The spike result shows queueing clearly: p95 rose from about 417 ms at
concurrency 8 to about 1,496 ms at concurrency 32 while throughput remained
near 21 requests/second. This is useful bottleneck evidence for this deliberately
latency-bound local provider, but target-environment sizing requires a longer
test with production network, models, databases, and SLOs.

## Reproduction shape

Start the gateway and local fault provider using the experiment-generated
configuration, then run `scripts/load_test.py` with `--scenario`, `--requests`,
`--concurrency`, `--process-pid`, and `--output`. The tool exits non-zero for
unexpected statuses or transport errors and records percentiles, throughput,
attempt/retry/cache/fallback ratios, budget/rate rejects, process CPU/RSS, and
backend error classes.
