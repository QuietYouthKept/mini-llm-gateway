# Reproducible experiment runbook

`scripts/run_experiment.py` creates one immutable evidence directory per run:

```text
evidence/load/<run_id>/
  manifest.json
  requests.jsonl
  summary.json
  latency.csv
  traces/README.md
  report.md
```

The harness stores request IDs, timings, token targets and response metadata only.
It deliberately excludes API keys, prompt bodies and completion bodies.  The provider
mode is mandatory in every manifest, so Stub and real-provider runs cannot be mixed in
a single report.

Start the local gateway, then run a deterministic Stub baseline:

```powershell
python scripts/run_experiment.py --provider-mode stub --provider-name mock_fast --provider-model deterministic --config config/config.yaml --requests 200 --concurrency 32 --shape spike --run-id stub-spike-c32
```

For a real provider, enable its existing OpenAI-compatible configuration, inject its
key through the environment, and use a distinct run ID:

```powershell
$env:GW_EXPERIMENT_API_KEY = "<gateway-client-key>"
python scripts/run_experiment.py --provider-mode real --provider-name openai-compatible --provider-model <model> --requests 20 --concurrency 1 --run-id real-smoke-01
```

### DeepSeek profile

The checked-in configuration includes a `deepseek` Provider and `deepseek-chat`
profile. In the same PowerShell session that starts the gateway, set
`DEEPSEEK_API_KEY`; the gateway process must inherit that environment variable.
The configured base URL is `https://api.deepseek.com` because the adapter itself
adds `/chat/completions`.

```powershell
cd 'D:\面试\github-projects\mini-llm-gateway'
$env:DEEPSEEK_API_KEY = '<keep this private>'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# Run this in a second PowerShell after the gateway is ready. It calls the
# gateway using demo-key; only the gateway process needs DEEPSEEK_API_KEY.
.\.venv\Scripts\python.exe scripts/run_experiment.py --provider-mode real --provider-name deepseek --provider-model deepseek-flash --profile deepseek-chat --requests 20 --concurrency 1 --run-id deepseek-smoke-01
```

This profile deliberately has no mock fallback: it prevents an apparent real
Provider success from actually being a local response. For streaming runs use
`scripts/run_experiment.py --stream`; it records TTFT, chunk count and
inter-chunk p95 separately from total latency. Use
`--disconnect-after-chunks N` for cancellation propagation evidence. Streaming
responses are intentionally not cached.

DeepSeek reports input usage that includes message/protocol overhead not visible
to the local character estimator. The default config therefore reserves a 128
token input floor and settles the Provider-reported total afterwards. This is a
conservative admission envelope, not a claim that every prompt contains 128
user-visible tokens.

The checked-in real-provider configuration uses a five-second end-to-end
deadline. This remains separate from the 30-second provider HTTP timeout: the
gateway deadline is the client-facing protection and is intentionally shorter.

The token estimator uses DeepSeek Flash's peak cache-miss rates for conservative
budget accounting: $0.30 per million input tokens and $1.20 per million output
tokens. These are a budget estimate, not an invoice: upstream prompt-cache and
off-peak discounts require Provider billing details that are not exposed by the
basic chat response.

Do not use real-provider results to claim gateway throughput. Compare only runs with
the same `provider.mode`, workload shape, config hash and machine context.  For each
comparison, keep a control group; for example cache ratio `0` versus `.9`, or one
gateway instance versus two behind the same load balancer.

Latency attribution is intentionally conservative:

- `provider_duration_ms` is the sum of recorded provider attempts.
- `gateway_overhead_ms` is end-to-end latency minus those attempts, so it includes
  cache, budgets, routing, retry delays, persistence, and client-side overhead.
- The process currently invokes providers directly and has no provider pool. It emits
  a `provider.queue_wait` trace span marked `queueing=false`; it does not claim a
  provider queue-wait number.

The gateway records low-cardinality phase metrics under
`llm_gateway_phase_duration_seconds` and matching trace spans: `auth.duration`,
`rate_limit.wait`, `cache.lookup.duration`, `singleflight.wait`,
`budget.reserve.duration`, `routing.duration`, `provider.queue_wait`,
`provider.duration`, `budget.settle.duration`, and `audit.persist.duration`.
Correlate `request_id` from
`requests.jsonl` with the audit endpoint or the OTLP trace backend. Successful
OpenAI-compatible responses record `provider_request_id` in each audit attempt,
and the experiment harness copies those values into `provider_request_ids`.
