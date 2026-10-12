# Wave 6 test evidence index

All evidence paths below are relative to `E:\project-test-assets\01-gateway\results\wave6-fault-contract-20261012T030137Z`. The raw evidence is intentionally external to the source repository; it includes generated SQLite test databases and should not be uploaded wholesale.

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
