# Local real-process load evidence — 2026-08-21

Environment: Windows, Python 3.11.9, one Uvicorn process, SQLite WAL, mock
providers, `127.0.0.1:8876`. This is bounded local evidence, not a production
capacity claim.

| Scenario | Requests / concurrency | RPS | p50 / p95 / p99 ms | Error | Attempts/request | Cache hit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| cache-heavy | 20 / 5 | 118.15 | 28.33 / 82.41 / 89.08 | 0% | 0.20 | 0.80 |
| cache-miss | 20 / 5 | 48.07 | 88.55 / 136.12 / 143.65 | 0% | 1.00 | 0.00 |
| long-prompt | 3 / 1 | 9.44 | 102.04 / 122.61 / 122.61 | 0% | 1.00 | 0.00 |
| provider-timeout | 5 / 2 | 10.16 | 64.75 / 407.15 / 407.15 | 0% | 2.40 | 0.00 |
| retry-storm | 5 / 2 | 11.76 | 125.63 / 204.17 / 204.17 | 0% | 2.40 | 0.00 |
| constant (cold) | 5 / 2 | 3.36 | 492.32 / 1045.53 / 1045.53 | 0% | 1.00 | 0.00 |
| ramp | 5 / 5 | 21.26 | 131.92 / 179.77 / 179.77 | 0% | 1.00 | 0.00 |
| spike | 5 / 5 | 34.99 | 130.15 / 131.70 / 131.70 | 0% | 1.00 | 0.00 |
| soak smoke | 10 / 2 | 13.44 | 113.31 / 268.44 / 268.44 | 0% | 1.00 | 0.00 |
| provider-latency | 5 / 2 | 19.26 | 95.38 / 101.39 / 101.39 | 0% | 1.00 | 0.00 |

After the two 20-request workloads, the Uvicorn process reported 59.4 MB
working set, 45.1 MB private memory, 7 threads, and 1.03 seconds accumulated
CPU. The health endpoint and a chat request with caller-supplied request id were
also verified over the real socket. The process stopped and the port closed.

Two Uvicorn replicas sharing one SQLite database were also probed. Concurrent
60k-token reservations returned exactly one 200 and one 429; both audit rows
were readable through replica A. The same prompt missed each process-local
cache, and each replica independently admitted three requests for a configured
3/min client before its own fourth request returned 429. This verifies the
documented state scopes instead of implying a global limiter/cache.

The first harness invocation accidentally honored the workstation proxy and
received proxy-generated 502 responses without reaching Uvicorn. The harness
was corrected to use `httpx.AsyncClient(trust_env=False)` and to exit non-zero
on any error rate; all tabled results are from the corrected run.

The 10-request "soak" is only a workload-shape smoke test. It does not provide
hours-long leak or stability evidence; a real soak remains an operational run
to schedule in an environment without the demo client's 60/minute limit.
