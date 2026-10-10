# Wave 5.2 bounded performance rerun

Candidate: commit `5a474c208d3095e678469f307a7c7d549233e6b9`, image `sha256:44486db8bb69095129d72cb1303937df117d968ffae703b8e3055a021fd5dacf`. Isolated Compose; deterministic `mock_fast`; no paid provider. The first attempted matrix used the demo client's 60 requests/minute and 100,000-token budget, then the initial corrected loop stopped on an invalid `/live` JSON-body assertion. Those raw artifacts are preserved under `wave52-performance/` and `wave52-performance-rerun/`; neither is represented as a passing capacity result.

Final bounded matrix used an isolated config and synthetic `wave52-benchmark-client` with 10,000 requests/minute and 100,000,000 daily tokens. Each of 12 formal runs used seed 20261010, 10 seconds of duration-based warmup, and 30 seconds formal measurement. The gateway received normal HTTP Chat requests (not SSE); TTFT was therefore not measured. Container CPU/RSS were sampled every ~10 seconds, without configured CPU or memory quotas.

| Concurrency | Requests | Successful | Success rate | Mean run RPS | Per-run P95 range |
|---:|---:|---:|---:|---:|---:|
| 1 | 912 | 912 | 100% | 10.08 | 110–125 ms |
| 8 | 3,488 | 3,488 | 100% | 38.23 | 265–312 ms |
| 32 | 3,712 | 3,367 | 90.71% | 39.67 | 937–1,203 ms |
| 64 | 5,376 | 1,807 | 33.61% | 55.41 | 1,562–2,407 ms |

At 32 concurrency there were 240 `database_unavailable` and 105 `stream_finalization_unknown` outcomes. At 64 there were 3,234 `database_unavailable` and 335 `stream_finalization_unknown` outcomes. The worst observed P99 was 5,516 ms. Sampled peak Gateway CPU was 187.54%; peak RSS was 91.19 MiB. A post-load metrics scrape showed event-loop lag of 1 ms and database blocking-I/O admission rejections totaling 5,556; these are post-run gauges/counters, not a peak time-series query.

Before reconciliation, PostgreSQL contained 614 expired `reserved` rows with no request audit and no finalization. The explicit reservation reconciler released all 614 and produced release finalizations/audits. Final checks found 14,853 reservations (14,239 settled; 614 released), 14,853 finalizations (14,239 settle; 614 release), zero missing finalizations, zero state/operation mismatches, and zero duplicate request/reservation finalizations. Reconciliation restored terminal consistency but does not change the failed performance outcome.

Decision: **FAILED for release acceptance**. The 32/64-concurrency error and settlement-uncertainty rates are material reliability failures. Do not advertise these measurements as production capacity. Raw JSON/CSV, per-run manifests, exits, container stats, metrics scrape, and database state are retained beside this report.
