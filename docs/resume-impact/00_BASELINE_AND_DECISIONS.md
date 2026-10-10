# Baseline and Decisions — Resume Impact Sprint

Date: 2026-10-10
Baseline branch: `codex/wave51-release-closure`
Baseline/source SHA: `ecae81222810ac2ac7b85823b56f473cc7637644` (source inherited from `c9ddbe65f94f460a55ccae122261335a89e9eef2`)
Baseline tree: `7d6a655ac7ec4c3c2d06743afd7bcb96ceed4a35`
Sprint branch/worktree: `codex/resume-impact-sprint` / `E:\mini-llm-gateway-resume-impact`

## Verified starting point

- Original E worktree's tracked files are clean. It contains untracked historical evidence, large OCI archives and the recently created `docs/career-prep/`; these remain untouched. A separate E: worktree was created from the exact baseline. The branch did not exist before creation.
- Remote branch head equals baseline SHA. Existing workflow Run `38031772984` completed successfully on that SHA; this historical run is not a result of this sprint.
- This new worktree's independent Python 3.11.9 locked environment ran Ruff (0), compileall (0), pytest (207 passed, 1 skipped), and `coverage report --fail-under=80 --precision=2` (80.58%, exit 0). The skip is the PostgreSQL probe because this host invocation did not supply an isolated PG URL. The resulting suite is not identical to the CI run's reported 208 tests / 83.47%; later comparisons must use the same DB-backed gate.
- Current `Postgres` repository calls `connect()` for each operation; `connection.py` invokes `psycopg.connect` at line 171 and uses 1s connect / 3s statement / 1s lock limits. There is no `psycopg_pool` dependency or pool lifecycle. DNS address caching already avoids repeating resolver work for a single DNS host; it does not reuse PostgreSQL sessions.
- `BoundedBlockingIO` uses a process-wide maximum of 8 workers, split across lanes; prior R10 source-overlay used 3 regular DB, 3 finalization, 1 Redis, 1 default worker, with bounded in-flight slots and a 250ms admission wait. The finalization lane had zero rejects in the prior after-source sample; ordinary DB lane had 3,733 rejects at the post-load scrape.
- Prior matched-resource R10 source-overlay (deterministic Mock HTTP, not a newly built source image): c32 success 80.35%→71.02% (1,113 after-source admission rejections); c64 28.42%→80.08% (816 rejections, max P99 5,565ms). It removed `database_unavailable` and `stream_finalization_unknown` from the after-source observations, but R10 remains FAILED. Existing after-source DB had 13,507 settled reservations / receipts / attempts, no duplicate receipts, no expired reservations, and no reconciliation.
- Observability baseline is partial: `/metrics` and gateway logs work, but the evidence says no Prometheus server API query, no trace backend query, and no end-to-end request-ID/trace/database-operation correlation.
- Existing Compose project names include several other repositories and prior Wave environments. No global Docker cleanup or stopping unrelated projects is allowed. Proxy environment variables were absent in this process; Docker context is `desktop-linux`, Engine/Client 28.3.3, Buildx 0.27.0.

Raw sprint baseline logs are stored outside the repository at `E:\mini-llm-gateway-resume-impact-evidence\`. Previous raw source-overlay evidence remains under the original worktree's `evidence/wave5/release-closure/` and is read-only.

## Decisions and unchanged acceptance

1. **Performance comes first.** Instrument/measure connection creation, connection wait, per-operation duration, executor admission/queue, CPU/RSS and database state before changing worker count or introducing a pool. The source proves connection churn exists, but does not prove it dominates the c32/c64 bottleneck. No pool will be added unless measured benefit and per-instance/aggregate connection limits are explicit.
2. **Keep settlement semantics immutable.** Do not weaken receipt uniqueness, transaction boundaries, usage provenance, finalization lane or audit to improve request success. Normal-load reservation state/receipt/budget invariants remain hard gates; expected overload rejections stay in the failure denominator.
3. **Observability reuses existing code.** Add only the smallest isolated Collector + Prometheus + trace backend needed to query real traces/metrics and correlate request ID. A running container or `/metrics` 200 alone is not acceptance. Prometheus labels remain low-cardinality and contain neither request ID nor prompt.
4. **Choose option B: a real TCP-level PostgreSQL COMMIT acknowledgment-loss test.** The audited cost/latency route is not a contained change: `RoutingService` only implements priority order and the domain/configuration has no validated per-provider cost plus latency-history contract. A correct scorer would require schema/loader/mapper/API/evaluation updates and explicit unknown-data, deadline-normalization, and circuit policy. That crosscut is disproportionate to this sprint. The Commit Unknown test is more directly tied to the gateway's hard reliability invariant. It only counts if a proxy drops the server's actual COMMIT acknowledgment after PostgreSQL accepted the transaction; a mocked exception is not evidence.
5. **Docker/release gates remain version-bound.** At most two targeted BuildKit network attempts, no TLS weakening. Current-source image acceptance requires a clean build, digest, smoke, scan, and two build identity comparison. Old image findings cannot be assigned to the new source. R06/R08/R09 and all R01–R11 statuses remain unchanged until their exact gate evidence is produced.
6. **Demo is integration only.** Provide one offline deterministic CLI demo that consumes existing flows/results; do not add a UI or claim benchmark results as live production traffic.

## Scope and expected evidence

Sprint limits: (A) measured DB/concurrency reliability; (B) real Prometheus and trace query/correlation; (C) one opt-in cost/latency routing capability; plus a lightweight demo and resume evidence. Each experiment must record command, exit code, SHA, environment, image identity if applicable, full denominator, raw log/JSON, DB invariants, and limitations. The acceptance targets are unchanged: no ignored errors, no invented request success, no lowering thresholds, no unbounded queue, no fake PASS. `RELEASE_READY` can only be true if every required R01–R11 gate is actually accepted.

## Work environment caveat

The shell began in the D: worktree. One attempted `uv run --offline python --version` resolved that old worktree's `.venv` and adjusted two installed packages there before the location issue was noticed. No D: source or history command was run afterward; no cleanup/restore was attempted. This is explicitly disclosed for operator review rather than claiming D: was untouched. All subsequent sprint work uses the new E: worktree/environment.
