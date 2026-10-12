# Post-token stream failure report

## Result

One deterministic real-TCP scenario passed on Windows with Uvicorn, two synthetic Provider instances, Toxiproxy 2.12.0 and an isolated temporary SQLite database. The client parsed exactly three non-empty message chunks before a downstream `reset_peer` toxic was installed. A delayed fourth frame triggered the reset.

Observed client events were `message, message, message, error`; the error code was `provider_failed`, and no `done` event was sent. Provider A had one request and one `error` attempt; Provider B had zero requests. The durable request audit contained one row with `partial_provider_error`. The reservation ended `settled`, with exactly one `settle` finalization. This is one scenario execution, not a probability or reliability-rate claim.

The initial experiment stalled the provider without a subsequent frame and produced `provider_timeout`, not a TCP reset. That failure is preserved as `fault-provider/toxiproxy-run.log` and its exit code; it motivated the trigger-frame version. A later final rerun passed (`fault-provider/toxiproxy-final.log`, exit code 0). Both pass and fail artifacts remain external to Git under the evidence root.

## Reproduction

From the isolated worktree, set `TOXIPROXY_SERVER` to the verified binary, `WAVE6_EVIDENCE_DIR` to the external evidence `fault-provider` directory, and run:

```powershell
uv run pytest -q tests/integration/test_toxiproxy_stream_reset_e2e.py --junitxml <evidence>\fault-provider\toxiproxy-final-junit.xml
```

The test creates only loopback listeners and an isolated SQLite file under pytest's external basetemp. It does not use a shared PostgreSQL/Redis service.

## Limits

Not tested here: PostgreSQL receipt/audit persistence under this exact network fault, repeated reset seeds, client disconnect in this same test, provider A/B capacity, and high-concurrency behavior. The standard full suite skips this opt-in Toxiproxy case unless explicitly enabled.
