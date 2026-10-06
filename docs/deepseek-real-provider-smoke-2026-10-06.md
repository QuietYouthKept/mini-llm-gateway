# DeepSeek real-provider smoke evidence — 2026-10-06

## Scope

This is a small-flow semantic and accounting validation, not a throughput or
production-capacity claim. The gateway sent 20 requests to the real
`deepseek-flash` model through the `deepseek-chat` profile.

- Evidence directory: `evidence/load/deepseek-smoke-05/`
- Provider mode: `real`; no Mock fallback
- Shape: constant, concurrency 1, 10 disjoint warmup requests
- Prompt cache: 0% hit rate in the recorded requests
- Config SHA-256: `858140651795cc1ea8646464b7161ebcb6bf9a50623984b930d36c0bd61708ea`
- Source provenance: baseline commit `af9cbe32dd16cb93bea081d750abcbc4ca232e6f`
  plus dirty-worktree diff SHA-256
  `f6a19de2d4789cccf02bd75f9a149535810aca15ea594311e32fe7132e7b1d6c`

## Results

| Measure | Result |
| --- | ---: |
| Successful requests | 20 / 20 (100%) |
| RPS | 1.590 |
| End-to-end p50 / p95 / p99 | 547 / 922 / 1000 ms |
| Provider-attempt p95 | 906 ms |
| Gateway-overhead p95 | 33 ms |
| Provider calls per API request | 1.0 |
| Retry amplification | 0.0 |
| Actual input / output tokens | 1288 / 752 |
| Estimated cost | $0.001287 |
| Audited upstream request IDs | 20 / 20 |

## Interpretation

At concurrency 1, the p95 latency is dominated by the upstream Provider (906
ms versus 33 ms gateway overhead). The load client reports queue wait because
it schedules all 20 requests behind its own concurrency-1 semaphore; that is
not evidence of a gateway or Provider queue. The gateway has no bounded
Provider pool and therefore reports `provider.queue_wait` only as an explicit
non-queueing trace span.

The first real run exposed a budget settlement failure: Provider-reported input
usage includes protocol/system overhead beyond the local prompt estimator. The
recorded run uses the corrected 128-token input reservation floor and has no
settlement failures. Cost uses DeepSeek Flash peak cache-miss prices configured
as a conservative estimate; it is not an invoice or a cache-discount estimate.

## Remaining validation

- Run the load matrix at concurrency 8, 32, and 64 against Stub providers
  first; keep real-provider traffic small.
- Run a separate low-volume DeepSeek SSE smoke test before publishing real
  Provider TTFT claims; gateway-side SSE support is now implemented.
- Run the two-replica probes with Redis/PostgreSQL before making any
  deployment-wide consistency claim.
