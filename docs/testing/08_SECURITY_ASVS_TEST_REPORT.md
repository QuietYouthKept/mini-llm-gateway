# Security verification report (ASVS-oriented)

This is a scoped evidence map, not an ASVS certification or full Level 1/2 assessment. OWASP currently identifies ASVS 5.0.0 as its latest stable version; requirement identifiers are version-dependent, so any formal traceability must pin the version. See the [OWASP ASVS project](https://owasp.org/projects/asvs?tab=meet-the-asvs).

## Executed

- Existing Security Eval: 8/8 passed (see `security-eval.log` and exit code).
- Local credential-pattern scan: passed on tracked source after explicitly staging this wave's source, tests and docs; result reports paths only, never matched contents.
- Contract/property tests reject boolean values in numeric Chat request fields and validate malformed/overlong input behavior.
- Dataset guardrail evaluation inspected 662 rows (546 train, 116 test) and emitted aggregate outcomes only; no prompt text or row identifiers were published.

## Partial / not tested

The supplied Parquet provenance, license and label semantics are unverified. Observed rule outcomes are not true-positive/false-positive rates, model-safety results or general prompt-injection resistance. No live provider, cloud, production secret, container scan, penetration test, TLS deployment, authorization matrix, rate-limit abuse test, or isolated PG/Redis security assessment was run. Historical image scan findings (44 High) remain open and are not cleared by this report.

## Disposition

Security Eval PASS applies only to that repository-defined 8-case evaluation. Overall security acceptance remains PARTIAL; do not claim ASVS compliance.
