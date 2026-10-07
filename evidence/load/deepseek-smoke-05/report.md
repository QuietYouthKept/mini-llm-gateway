# Gateway experiment report

- Run: `deepseek-smoke-05`
- Provider mode: **real** (do not compare directly with the other mode)
- Provider/model: `deepseek` / `deepseek-flash`
- Workload: constant, concurrency 1, seed 42
- Result: 20/20 success; p95 922.0 ms; 1.59 RPS.

## Attribution

- Gateway-overhead p95: 33.0 ms (end-to-end latency minus recorded provider attempts).
- Provider-duration p95: 906 ms.
- Retry amplification: 0.0; provider calls/API request: 1.0.
- Provider queueing is not implemented in this gateway; `provider.queue_wait` trace spans make that limitation explicit.

`requests.jsonl` is sanitized metadata keyed by local request ID and includes upstream provider request IDs when exposed. Prompts, completions, and API keys are intentionally absent.
