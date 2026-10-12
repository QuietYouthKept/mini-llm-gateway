# Wave 6 test evidence index

All evidence paths below are relative to `E:\project-test-assets\01-gateway\results\wave6-fault-contract-20261012T030137Z`. The raw evidence is intentionally external to the source repository; it includes generated SQLite test databases and should not be uploaded wholesale.

## Remote GitHub CI (commit 95574cd11d59f851e92baff2562a82263f32721e)

- Run: [38201945812](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38201945812)
- Evidence Artifact ID 11725997608; downloaded ZIP `remote-ci/gateway-ci-evidence.zip`; extracted review copy under `remote-ci/ci-evidence/`.
- Validation Artifact ID 11725997613; downloaded ZIP `remote-ci/gateway-evidence-validation.zip`; extracted result under `remote-ci/validation-artifact/`.
- Local independent verification: `remote-ci/artifact-validation-local.json`; 160 expected/actual files, zero missing, zero extra, zero hash/size mismatches; manifest SHA-256 `61046c3217d67b716f081fc4ac68e558ae192712b2d3b464936ff72cf06b7d7b`.
- Remote pytest JUnit/log report 247 passed, 1 skipped. Combined coverage was 84.46%, line 87.02%, branch-rate submetric 72.94%; do not conflate the branch-rate submetric with the configured combined coverage gate.
- PostgreSQL / Redis / HTTP-SSE / Provider Contract raw evidence is in `remote-ci/ci-evidence/postgres/`, `redis/`, `http-sse/`, and `provider/`.

| Evidence | Path |
|---|---|
| Full pytest log, status and JUnit | `coverage/pytest-final.log`, `coverage/pytest-final.exitcode`, `coverage/pytest-final-junit.xml` |
| Pytest-only coverage | `coverage/coverage-final.xml`, `coverage/coverage-final-gate.log`, `coverage/coverage-final-gate.exitcode`, `coverage/.coverage-pytest-final` |
| Focused reliability suite | `reports/reliability-focused.log`, `.exitcode`, `-junit.xml` |
| Ruff / compileall / evals / secret scan / diff check | `reports/` (and target-specific final Ruff reports under `fault-provider/` and `dataset/`) |
| Toxiproxy reset pass and retained initial failure | `fault-provider/toxiproxy-final.log`, `toxiproxy-final.exitcode`, `toxiproxy-retry.log`, `toxiproxy-run.log`, `post-token-three-chunk-reset-*.json` |
| Hypothesis aggregate and local Gateway logs | `reports/hypothesis-api-result.json`, `reports/hypothesis-api.log`, `reports/hypothesis-api.exitcode` |
| Schemathesis final and failed iterations | `reports/schemathesis-final.log`, `schemathesis-final-junit.xml`, plus `schemathesis-focused.*`, `schemathesis-retry.*` |
| Dataset aggregate-only outcomes | `dataset/prompt-injection-guardrail-aggregate.json`, `dataset/evaluation.log`, `dataset/evaluation.exitcode` |
| Dataset and tool hashes/preflight | `reports/preflight.txt`, `reports/uv-sync.log`, `reports/uv-sync.exitcode` |

Raw prompt rows are not copied into evidence. The external test database files and temporary configs are local test fixtures and are not intended for publication.
