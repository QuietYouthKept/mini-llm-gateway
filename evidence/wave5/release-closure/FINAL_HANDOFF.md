# Wave 5.1 Final Handoff

Decision: **`RELEASE_CANDIDATE_NOT_ACCEPTED`**. This is a bounded closure of the executed work, not production approval.

## Verified candidate

- Branch: `codex/wave51-release-closure`
- Tested source: `c4ba57dafd380ca1d1a6ba39b40de0732d30a697`
- Local OCI manifest/image identifier: `sha256:9c85a88dba65c3e7ac1493690ea1fe9198821284021df8eca92f0267a3e600fb` (not a registry RepoDigest)
- Two independent no-cache OCI archives were byte-identical; both 60,738,048 bytes and SHA-256 `679f9eebeb1c4672e5967dbb0289ac2af28a2e7efed09d0afc68d701226b0a3b`.
- Compose project: `wave51-release-closure`, gateway `127.0.0.1:18151`. The first dependency startup window returned readiness 503; subsequent `/ready` returned 200. Synthetic TCP SSE returned 200 and message/usage/done; PostgreSQL showed settled reservation, one settle receipt and one request audit.

## Quality and database results

Ruff and compileall exited 0. Pytest: 204 passed, 1 skipped in 22.88 s; branch coverage 81.08%; independent 80% report gate exited 0. Functional and security evaluation completed successfully (security 8/8); Provider Contract 13 passed; TCP SSE 2 passed. PostgreSQL integration probe exited 0; Redis multi-client probe exited 0 with 10/20 rate-limit admissions, shared cache, lease expiry, stale-owner protection, and configured fail-open/closed behavior.

The PG probe established atomic rollback, replay idempotency, a single usage increment, and orphan reconciliation on real PostgreSQL. Its Commit Unknown case was synthetic exception injection after a completed commit; a network-level lost COMMIT acknowledgement and crash-boundary injection remain unproven.

## Release blockers

Trivy 0.75.0 found 3 Critical and 88 High findings in the exact candidate; no exception was approved. Two-version schema upgrade/rollback was not run. OTLP Collector → trace backend → query correlation was not run. Prometheus scrape/query, DNS rebinding/redirect egress controls, and the requested controlled performance matrix were not run. The historical PyPI TLS EOF remains unexplained, although host, Engine, BuildKit proxy tests and two clean builds now succeed.

Do not create a completion tag or deploy this image. See `RELEASE_GATE_SUMMARY.json`, the per-domain reports, and raw scan/test artifacts for the exact statuses. Development CI run [38015606740](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38015606740) passed for `de6d2a3e0d8a4a0b61afc75fbfe16d2c4beceda3` (205 passed, 84.02% coverage and the independent 80% gate). Evidence Artifact `11656405425` and validation Artifact `11656695290` were downloaded; local independent validation found 155 files, zero hash/size mismatches, and manifest SHA-256 `850ac4938b1594821c101e93ca817b6b293c1dbf56fabf2e56986a0004a37db8`. This CI pass does not clear the candidate's image CVE, rollback, network, observability or performance blockers.

## Evidence chain

The E-drive preservation package is outside the repository at `E:\mini-llm-gateway-wave51-preservation-20261010` with a SHA-256 inventory. The isolated source worktree is `E:\mini-llm-gateway-wave51`; the D-drive worktrees remain untouched. OCI build archives, scanner JSON/database cache, probe outputs and local gates are kept under this release-closure evidence directory but are not all intended for Git history. Keep the raw artifacts backed up with the manifest before any cleanup.

## Next independent work

1. Triage/remediate Critical/High findings on a new pinned base image; rerun scan and SBOM.
2. Implement a controlled PostgreSQL TCP fault proxy to drop the server acknowledgement after COMMIT; verify recovery from DB rows and process termination.
3. Build the prior committed image and complete old → new → old against one disposable schema, with data and readiness checks.
4. Add trace backend and Prometheus to the isolated stack, then query the same synthetic request across logs/metrics/traces.
5. Add DNS pinning/redirect/IP-class tests plus an enforced egress boundary.
6. Run a predeclared multi-round performance protocol against an identifiable baseline after security blockers are closed.
