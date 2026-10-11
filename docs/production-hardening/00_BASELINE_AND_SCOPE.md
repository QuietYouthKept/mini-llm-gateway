# Production hardening baseline and scope

## Version identity

- Repository: `QuietYouthKept/mini-llm-gateway`
- Base remote branch: `codex/dataset-evaluation`
- Source SHA: `4d067cc2bdd137218ad055e15bfaf85b1078644f`
- Source tree: `e6112a8b5b161cd632f6216799959c443ab1b42d`
- New isolated worktree: `E:\mini-llm-gateway-prod-hardening`
- New branch: `codex/p0-p1-production-hardening`
- Initial worktree state: clean
- `uv.lock` SHA-256: `76be330260e5a6f204c866d344eddb1fac96a07fd513e1a74b5496c0e6c9c5bf`
- `Dockerfile` SHA-256: `7924312e44711c135dbc22d78c264cd223d8760bf4a44fa929c82189d1d14d73`

The remote branch was read twice during preflight (GitHub branch API and `git ls-remote`); both returned the source SHA above. The existing `E:\mini-llm-gateway-dataset-eval` checkout was not changed: it remains on the same SHA with its 19 pre-existing modified/untracked dataset-evaluation paths. Its contents are not part of this worktree or this branch.

## Prior remote CI and evidence

GitHub Actions Run `38070902799` is completed/successful for branch `codex/dataset-evaluation` and exactly the source SHA above. The run reports 210 passed in its Linux test job. The run has Evidence Artifact `11676278972` and Validation Artifact `11676124229`; GitHub reports both unexpired (557,537 and 453 bytes respectively). Prior independent validation recorded 155 manifest files, zero missing/extra/hash/size mismatches. This is inherited baseline evidence, not a result of the present hardening branch.

## Host and tool preflight (2026-10-11 local time)

- Windows 11, Python on PATH `3.8.3` (below this project's `>=3.11` requirement); `uv 0.11.23` is available.
- Docker Desktop Linux engine `28.3.3`, BuildKit `v0.23.2`, Buildx `v0.27.0`; active context `desktop-linux`, 24 engine CPUs, 16,351,653,888-byte Docker memory allocation.
- WSL reports Ubuntu 24.04 / WSL 2. Windows reports 24 logical processors and approximately 4.9 GiB free physical memory at preflight. E: has approximately 57.5 GiB free.
- The latest user-confirmed local proxy is `127.0.0.1:7890`; TCP and HTTPS access to PyPI through it were verified. The isolated Docker candidate build used `http://host.docker.internal:7890` as BuildKit proxy args. TLS verification remained enabled; no proxy credentials or environment values were recorded.
- GitHub SSH with the existing `id_ed25519_quietyouthkept` identity returned `QuietYouthKept`. No key was created or modified.
- Docker had 18 unrelated containers running at preflight. None were stopped, inspected for secrets, or modified. No new experiment containers have yet been started.

Raw preflight, Docker environment/resource snapshot, source manifest, and identities are kept outside Git under `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z\`.

## Existing known failure and limits

The prior overnight experiment on a fresh historical environment reported an 8-concurrency, cache-off cell with 1,984/1,984 HTTP 503 (`database_unavailable`), after two successful 8-concurrency cells. Its matrix stopped at 12/36; concurrency 32/64 were not run. Two expired reservations were later reconciled to `released`; the post-reconciliation snapshot reported no reserved/uncertain reservations and no duplicate finalization receipts. This later snapshot does not prove the state was clean at the time of failure.

The historical run did not capture failure-time SQLSTATE, `pg_stat_activity` wait event, blocking PID, lock-wait duration, or connection-acquire timing. Same-client advisory-lock contention plus short server deadlines is a hypothesis only. No root cause is confirmed, and no performance improvement is claimed.

The checked-in `EVENT_LOOP_BLOCKING_AUDIT.md` describes an earlier Wave 4 run, not this source SHA. It records `/ready` missing a 2-second response under 20 concurrent PostgreSQL outage requests, `/live` at 1.547 seconds, and maximum request duration 9.594 seconds. This is historical evidence; it must not be represented as a measurement of this candidate.

## Scope and guardrails

Priority is a fresh isolated PostgreSQL/Redis/Gateway diagnosis, failure-time server evidence, and a minimal causal fix only if the evidence is sufficient. No 36-cell benchmark begins before correctness and resource safety are demonstrated. The pre-existing Docker workloads and all historical evidence are protected. No production endpoint, real database, paid provider, force push, Main merge, tag, or deployment is authorized.

The current baseline remains a candidate engineering branch, not a production release. R01-R11 and production approval will be reassessed from new-source evidence only.
