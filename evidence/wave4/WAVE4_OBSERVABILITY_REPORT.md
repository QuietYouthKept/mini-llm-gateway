# Wave 4 Observability Report

## Status: PARTIAL / runtime backend validation not completed

Application metrics/tracing libraries and Prometheus/Grafana/Collector configuration exist, and request ID/decision trace/provider attempt paths were retained. This Wave did not start an OpenTelemetry Collector plus metrics backend to verify trace-to-metric/log correlation end to end. There is no runtime proof that a request links request ID, trace ID, selected provider/profile, attempt number, fallback reason, reservation, receipt and final HTTP status in exported telemetry.

The security property that API key/Authorization and full prompt must not enter exported spans was not independently validated against a live collector. Do not claim trace redaction or alert/dashboard readiness from config presence alone.

Staging exercised normal SSE, cancellation, PG outage, Redis outage, settlement-unknown and SIGTERM code paths, but no correlated span/metric/log export was captured. Required next: launch isolated Collector and Prometheus, inject provider timeout, 429/5xx, circuit open, budget reject, PG/Redis unavailable, stream cancel and settlement unknown; query exported trace/metric/log records for linkage and secret/prompt absence. Distinguish per-replica metrics from aggregate metrics.
