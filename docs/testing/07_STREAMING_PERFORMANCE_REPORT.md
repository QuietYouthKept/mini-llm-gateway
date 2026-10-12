# Streaming performance report

No throughput, latency, concurrency-capacity, CPU, RSS, backpressure, or soak experiment was run in this wave. Available host RAM was below the task's 6 GiB floor, and other projects' containers were present; starting additional service containers or high-concurrency work would have violated the resource gate. Consequently RPS, p50/p95/p99, time-to-first-token, slow-consumer behavior under load, and recovery capacity are `NOT MEASURED`.

The real-TCP reset scenario is a correctness/fault-injection test, not a performance test. It establishes only the observed three chunks, terminal SSE event, attempt choice and SQLite accounting state in that single execution. Historical Wave 4/5 capacity figures are not revalidated here and must retain their original provenance and caveats.
