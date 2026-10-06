# Gateway experiment report

- Run: `streaming-local-smoke-20261006-r3`
- Provider mode: **stub** (do not compare directly with the other mode)
- Provider/model: `mock_fast` / `deterministic`
- Workload: constant, concurrency 1, seed 42
- Result: 4/4 success; p95 391.0 ms; 2.845 RPS.

## Attribution

- Gateway-overhead p95: 33.0 ms (end-to-end latency minus recorded provider attempts).
- Provider-duration p95: 358 ms.
- Retry amplification: 0.0; provider calls/API request: 1.0.
- Provider queueing is not implemented in this gateway; `provider.queue_wait` trace spans make that limitation explicit.

`requests.jsonl` is sanitized metadata keyed by local request ID and includes upstream provider request IDs when exposed. Prompts, completions, and API keys are intentionally absent.
