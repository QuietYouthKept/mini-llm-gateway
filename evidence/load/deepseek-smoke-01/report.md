# Gateway experiment report

- Run: `deepseek-smoke-01`
- Provider mode: **real** (do not compare directly with the other mode)
- Provider/model: `deepseek` / `deepseek-flash`
- Workload: constant, concurrency 1, seed 42
- Result: 7/20 success; p95 953.0 ms; 1.877 RPS.

## Attribution

- Gateway-overhead p95: 906.0 ms (end-to-end latency minus recorded provider attempts).
- Provider-duration p95: 608 ms.
- Retry amplification: 0.0; provider calls/API request: 0.15.
- Provider queueing is not implemented in this gateway; `provider.queue_wait` trace spans make that limitation explicit.

`requests.jsonl` is sanitized metadata keyed by local request ID and includes upstream provider request IDs when exposed. Prompts, completions, and API keys are intentionally absent.
