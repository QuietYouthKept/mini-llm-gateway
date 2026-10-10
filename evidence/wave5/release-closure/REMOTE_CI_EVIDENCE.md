# Remote CI and Evidence Verification

Status: PASS for Development CI and artifact integrity only; not release acceptance.

- Workflow run: [38015606740](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38015606740)
- Tested commit: `de6d2a3e0d8a4a0b61afc75fbfe16d2c4beceda3` on `codex/wave51-release-closure`
- Conclusion: Success; job `test (3.11)` completed in 1m06s.
- Pytest: 205 passed in 15.87s.
- Branch coverage: 84.02%; independent coverage threshold gate passed at 80%.
- Functional Eval: 7/7; Security Eval: 8/8.
- PostgreSQL, Redis adapters, Redis two-replica HTTP, HTTP/SSE, Provider Contract, secret scan, dependency audit, and repository hygiene steps passed.
- Evidence Artifact ID: `11656405425`, name `gateway-ci-evidence-de6d2a3e0d8a4a0b61afc75fbfe16d2c4beceda3-run-38015606740`.
- Validation Artifact ID: `11656695290`, name `gateway-evidence-validation-de6d2a3e0d8a4a0b61afc75fbfe16d2c4beceda3-run-38015606740`.
- Downloaded and independently checked: 155 manifest entries, 155 actual evidence files, no missing/extra files, zero SHA/size mismatches; manifest SHA-256 `850ac4938b1594821c101e93ca817b6b293c1dbf56fabf2e56986a0004a37db8`.
- Downloaded files and the runner validation report are preserved under `remote-artifacts/`.

The run establishes Development CI and the Evidence upload path. It does not execute the unresolved release gates: Critical/High image vulnerability disposition, real wire-level Commit Unknown, old/new rollback, end-to-end telemetry query, production egress controls, or the controlled performance matrix.
