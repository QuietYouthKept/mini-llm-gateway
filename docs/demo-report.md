# Demo Report

Generated: 2026-08-15T12:40:47

**Status: 12/12 scenarios passing**

| Scenario | Expected | Actual | Result |
| --- | --- | --- | --- |
| auth: missing key | 401 auth_failed | 401 auth_failed | PASS |
| chat: happy path | 200 provider=mock_fast | 200 provider=mock_fast | PASS |
| fallback: error -> stable | 200 provider=mock_stable | 200 provider=mock_stable | PASS |
| fallback: timeout -> fast | 200 provider=mock_fast | 200 provider=mock_fast attempts=['timeout', 'timeout', 'success'] | PASS |
| guardrail: injection blocked | 400 guardrail_blocked | 400 guardrail_blocked | PASS |
| rate limit: burst | 3x 200 then 429 | statuses=[200, 200, 200, 429] | PASS |
| budget: token exceeded | 429 token_budget_exceeded | 429 token_budget_exceeded | PASS |
| cache: first request (miss) | 200 cache_hit=false | 200 cache_hit=False | PASS |
| cache: second request (hit) | 200 cache_hit=true | 200 cache_hit=True provider=mock_fast | PASS |
| audit: request replay | 200 with attempts + decision_trace | 200 attempts=1 | PASS |
| openai-compatible | 200 chat.completion | 200 object=chat.completion | PASS |
| observability: metrics | 200 prometheus text | 200 lines=138 | PASS |

### Decision trace — chat: happy path

Every routing decision is recorded with a reason:

    [{"step": "streaming_checked", "allowed": true}, {"step": "rate_limit_checked", "allowed": true, "limit_per_minute": 60}, {"step": "profile_resolved", "profile": "fast-chat", "intent": "low_latency"}, {"step": "guardrail_input_checked", "allowed": true}, {"step": "cache_miss", "reason": "no exact match", "key": "cache_22c20f4ed57fb115e2182966"}, {"step": "budget_checked", "remaining_before": 100000}, {"step": "provider_selected", "provider": "mock_fast", "reason": "primary candidate (priority=1)"}, {"step": "guardrail_output_checked", "allowed": true}, {"step": "budget_committed", "remaining_after": 99986}]

### Decision trace — fallback: error -> stable

Every routing decision is recorded with a reason:

    [{"step": "streaming_checked", "allowed": true}, {"step": "rate_limit_checked", "allowed": true, "limit_per_minute": 60}, {"step": "profile_resolved", "profile": "fallback-chat", "intent": "demo_fallback"}, {"step": "guardrail_input_checked", "allowed": true}, {"step": "cache_miss", "reason": "no exact match", "key": "cache_444d7d3077b01d299ea5fbf8"}, {"step": "budget_checked", "remaining_before": 99986}, {"step": "provider_failed", "provider": "mock_error", "reason": "error", "error_code": "provider_failed"}, {"step": "provider_failed", "provider": "mock_error", "reason": "error", "error_code": "provider_failed", "retry_index": 1}, {"step": "provider_selected", "provider": "mock_stable", "reason": "fallback candidate after 1 failed attempt(s)"}, {"step": "guardrail_output_checked", "allowed": true}, {"step": "budget_committed", "remaining_after": 99975}]

### Metrics snapshot (excerpt)

    llm_gateway_requests_total{endpoint="/v1/chat",status="success"} 8
    llm_gateway_requests_total{endpoint="/v1/chat",status="guardrail_blocked"} 1
    llm_gateway_requests_total{endpoint="/v1/chat",status="rate_limit_exceeded"} 1
    llm_gateway_requests_total{endpoint="/v1/chat",status="token_budget_exceeded"} 1
    llm_gateway_requests_total{endpoint="/v1/chat/completions",status="success"} 1
    llm_gateway_fallbacks_total 2
    llm_gateway_cache_hits_total 3
    llm_gateway_cache_misses_total 7
