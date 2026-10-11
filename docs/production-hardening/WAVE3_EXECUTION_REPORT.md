# Wave 3 execution report

Date: 2026-10-11 10:59 UTC
Branch: `codex/p0-p1-production-hardening`
Repository HEAD during investigation: `0acc85eb5f9d856bc6aa9050e8f69edbf6ee6500`
Source/image used by isolated diagnostics: commit `3a06d06198757f1eeb306b7d8d2e0d46e842df25`, image `sha256:eb587db5331fdd4f13bd579344a38a8c2839c5c98f42b9f47a4ff31f561b70d2`
External evidence root: `E:\project-test-assets\01-gateway\results\production-hardening-wave3-20261011T055445Z`

## Executive status

| Area | Status | Evidence-based conclusion |
| --- | --- | --- |
| Scoped PostgreSQL `55P03` reproduction | **PASS (narrow scope)** | Same-client advisory-lock waits produced `503 database_lock_timeout`; PostgreSQL logs showed SQLSTATE `55P03`. This does not prove the cause of the historical 1,984/1,984 outage. |
| Formal capacity matrix | **FAILED as a capacity acceptance gate; PASS for accounting integrity** | All 36 cells ran with 0 accounting invariant issues. 73,101 formal requests produced 53,729 HTTP 200 and 19,372 controlled `503 database_admission_overloaded` responses. c=32 and c=64 do not meet an all-success capacity objective under these limits. |
| URL/config/Provider unit tests | **PASS** | Current source tests: 33 passed, exit 0. Runtime DNS-rebinding, socket-peer and egress-policy tests remain unexecuted. |
| PostgreSQL SIGKILL / isolated restore | **PASS (synthetic scope)** | PostgreSQL exited 137 after SIGKILL; persisted matrix counts and a deterministic 32-row probe digest were unchanged after restart. A custom-format dump of that probe schema restored into an isolated, network-none PostgreSQL container with the same row count and digest. Full production-scale backup/restore is not proven. |
| Redis outage / recovery | **PASS (isolated behavior)** | During Redis outage `/live` stayed 200, `/ready` returned 503, and chat returned `rate_limit_backend_unavailable` with one durable error audit and no provider attempt/reservation/receipt. After Redis restart readiness returned 200 and a new synthetic request settled normally. |
| Current image vulnerability gate | **FAILED / HUMAN SECURITY REVIEW REQUIRED** | The retained Trivy 0.75.0 scan for the image sourced from `3a06d06` reported 44 High findings across 8 CVEs. This Wave 3 run did not rebuild or rescan an image. |
| Production-like release acceptance | **BLOCKED** | Disaster recovery, Redis failure/recovery, full egress controls, upgrade/rollback, alert delivery and full SSE failure matrix remain incomplete. |

No application source or container configuration was changed during this continuation. The formal matrix's external evidence script was corrected to match the actual schema and to avoid counting warmup usage in formal token deltas. The first two attempts are retained as aborted setup attempts and excluded from the formal 36-cell result.

Fresh local verification of the unchanged application source plus this documentation change: Ruff exit 0; compileall exit 0; full pytest **212 passed, 1 skipped**; pytest-only branch-aware total coverage **80.81%**, independent 80% gate exit 0; Functional Eval **7/7** exit 0; Security Eval **8/8** exit 0; TCP Uvicorn/SSE E2E **2 passed** exit 0; Provider/config/SSRF unit subset **33 passed** exit 0; tracked-file secret scan exit 0; `git diff --check` exit 0. Raw commands, logs, JUnit and coverage outputs are in `06-final-gates/` under the external evidence root. A first attempt at invoking eval/SSE used malformed PowerShell argument construction and is preserved separately; only the corrected `*-rerun` results above are valid.

## 1. PostgreSQL contention and the historical 503 incident

The isolated diagnostic used the candidate image, PostgreSQL 16, Redis 7 and deterministic local mock providers on an internal-only Docker network. Synthetic requests only were used; no paid provider traffic was possible.

- Clean single-client baselines: c=1, 8/8 returned 200; c=8, 16/16 returned 200. A clean 32-request c=8 burst returned 32/32, and controlled arrivals returned 16/16.
- Injected same-client budget advisory lock: requests waited on `Lock:advisory`; PostgreSQL server logs recorded SQLSTATE `55P03`; the application returned `503 database_lock_timeout` and persisted request audits. Cross-client controls showed that lock contention is not equivalent to an outage of every client, although a control attempted while the synthetic key was rate/budget limited was not usable as a clean comparison.
- Near connection ceiling: 90 of 100 PostgreSQL connection slots were held by a disposable synthetic holder; a subsequent c=8/16 batch returned 16/16 with complete audit/reservation/receipt/attempt cardinalities.
- The historical overnight 1,984/1,984 `database_unavailable` failure remains **unexplained**: that run did not retain contemporaneous SQLSTATE, wait-event, blocker-PID and persistence snapshots. The reproduced `55P03` defect is a scoped finding, not a retroactive root-cause claim.
- A disposable PostgreSQL crash drill used `docker kill --signal KILL` (exit 0; container exit 137, not OOM), then an explicit container start. The 73,101 formal audit count, 20,198 settled synthetic reservations and a 32-row deterministic probe digest were identical before and after recovery. `/ready` was 503 while PostgreSQL was unavailable and returned 200 after dependency probes recovered. A chat request sent before readiness returned 503 `database_unavailable` without reservation/receipt/attempt; after readiness returned 200, a unique request completed with one provider attempt and one settled receipt. This is an isolated single-node crash/restart, not failover or HA.
- A custom-format `pg_dump` of only the synthetic `wave3_crash_probe` schema (32 deterministic rows) was restored into a separate PostgreSQL 16 container on `--network none`; restored row count and digest matched. This proves the dump/restore path for this small synthetic schema, not a full production-scale database backup or RPO/RTO.
- Redis was SIGKILLed in the disposable Compose project. `/live` remained 200 and `/ready` returned 503. A chat attempt returned `503 rate_limit_backend_unavailable`; the database recorded one error audit and zero provider attempts, reservations or receipts. After Redis restart, `/ready` returned 200 and a new request settled with one provider attempt/receipt. This does not test Redis HA or persistence guarantees.

The diagnostic evidence is under `03-historical-503-diagnostic/`, including `c1-single.json`, `c8-single.json`, clean burst/arrival probes, advisory-lock snapshots, server log extracts and connection-pressure artifacts. Files explicitly marked contaminated or invalid remain labeled as such and were not used as clean controls.

## 2. Formal capacity matrix

### Method and evidence

- 4 concurrency levels (`1, 8, 32, 64`) × 3 target cache ratios (`0%, 50%, 90%`) × 3 repetitions = **36 cells**.
- Each cell used a 10-second warmup and a 30-second formal interval. Gateway, PostgreSQL and Redis limits were respectively 2 CPU/1 GiB, 2 CPU/1 GiB and 1 CPU/512 MiB.
- The Gateway was pinned to the candidate image and used a synthetic local mock provider, synthetic API key/client and isolated PostgreSQL/Redis services. No third-party provider was enabled.
- For every formal request, the checker compared HTTP result, `request_logs`, cache-hit state, provider attempts, finalization receipt/reservation state and token-usage delta. PostgreSQL activity, locks, connection counts, container statistics and `/metrics` samples were retained per cell.
- Final formal run ID: `20261011T101129Z`; process exit code 0. Final progress: 36/36, `aborted=false`. Every cell recorded `accounting.issues=[]`.

Two earlier trials were not counted: one stopped after the verifier queried a nonexistent `token_budget_reservations.request_id`; a second stopped at a result-emission `NameError`. Their generated synthetic requests were retained and independently checked after correcting the verifier: 626 requests were present in those two formal windows, each with request audit, settled reservation, settlement receipt and provider attempt; usage delta equaled receipt tokens. The corrected official run used a unique run ID and independently verified its own 73,101 formal requests.

### Results

| Concurrency | Target cache | Requests | HTTP 200 | Success rate | Successful RPS avg (range) | Actual audit cache-hit avg | Mean of cell p95 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0% | 959 | 959 | 100% | 10.66 (10.30–10.93) | 0% | 113 ms |
| 1 | 50% | 1,679 | 1,679 | 100% | 18.66 (18.40–18.83) | 54% | 110 ms |
| 1 | 90% | 3,790 | 3,790 | 100% | 42.11 (40.87–43.07) | 90% | 96 ms |
| 8 | 0% | 3,083 | 3,083 | 100% | 34.26 (33.87–34.53) | 0% | 300 ms |
| 8 | 50% | 6,069 | 6,069 | 100% | 67.43 (66.93–68.07) | 58% | 272 ms |
| 8 | 90% | 12,758 | 12,758 | 100% | 141.76 (134.30–145.97) | 91% | 202 ms |
| 32 | 0% | 4,265 | 1,949 | 45.7% | 21.66 (18.47–24.47) | 0% | 954 ms |
| 32 | 50% | 6,492 | 4,968 | 76.5% | 55.20 (53.27–57.80) | 50% | 871 ms |
| 32 | 90% | 11,692 | 11,363 | 97.2% | 126.26 (119.47–132.10) | 91% | 597 ms |
| 64 | 0% | 4,966 | 1,198 | 24.1% | 13.31 (13.07–13.47) | 0% | 1,548 ms |
| 64 | 50% | 7,135 | 2,196 | 30.8% | 24.40 (22.57–25.40) | 22% | 1,317 ms |
| 64 | 90% | 10,213 | 3,717 | 36.4% | 41.30 (39.27–43.70) | 35% | 678 ms |

Across all cells, **53,729/73,101 (73.5%)** requests returned 200 and **19,372** returned `503 database_admission_overloaded`. The system rejected overload rather than accepting unbounded work. This protects resource/accounting invariants but does **not** pass a full-success capacity gate at c=32/c=64. High-cache conditions improved throughput and reduced tail latency but did not prevent rejection at c=64.

### Persistent accounting final state

Read-only PostgreSQL aggregation for the official run ID confirmed:

- 73,101 formal `request_logs` rows.
- 38,459 cache hits (no reservation/receipt/provider attempt expected for those hits).
- 15,270 provider-attempt rows and 15,270 settlement receipts for successful cache misses.
- 457,830 settled tokens from receipts; per-cell usage deltas matched receipt token totals.
- 0 reservations without a finalization receipt; all synthetic-client reservations ended `settled`; no `reserved` rows remained.
- 0 accounting invariant issues across the 36 cell JSON files.

Raw evidence: `04-capacity-matrix/formal_capacity_matrix.py`, `formal-matrix-run3.command.txt`, `formal-matrix-run3.log`, `formal-matrix-run3.exitcode`, `matrix-progress.json`, `matrix-summary.json`, 36 `c*.json` cell files, `formal-matrix-aggregate.json`, `formal-matrix-final-accounting.txt`, `matrix-final-db-state.txt`, `matrix-final-health.json`, and the two separately retained aborted-attempt logs. `/live` and `/ready` returned 200 after the matrix. Recovery artifacts are under `07-failure-recovery/` (PG dump/restore, SIGKILL snapshots, Redis outage responses and database side-effect queries). These figures are a local, single-candidate, mock-provider test—not a general production capacity claim.

## 3. Image CVE triage

The retained scan is Trivy 0.75.0 against image `sha256:eb587...`, built from `3a06d06`, Debian GNU/Linux 13.7 (Trixie): 0 Critical, **44 High**, 63 Medium, 62 Low and 3 Unknown; 128 CycloneDX components. The 44 High package matches collapse to eight CVEs. Runtime package inspection found the listed shared libraries and tools in the image. The app does not intentionally invoke the privileged OS utilities, but their presence remains relevant under arbitrary code execution. The current runtime profile (`10001:10001`, read-only rootfs, all capabilities dropped, `no-new-privileges`) reduces attack surface; it is not a CVE waiver.

| CVE | Affected image packages / detected version | Debian Trixie status and relevant exposure | Disposition |
| --- | --- | --- | --- |
| CVE-2026-76642 | `bsdutils`, `libblkid1`, `liblastlog2-2`, `libmount1`, `libsmartcols1`, `libuuid1`, `login`, `mount`, `util-linux`; `2.41.5-0+deb13u1` family (`login`: `1:4.16.0-2+really2.41.5-0+deb13u1`) | Trixie vulnerable; issue concerns mount helper status/post-mount hooks. Image includes setuid `mount`; app does not call it. Debian lists a fix in forky/sid, not Trixie. | `HUMAN_SECURITY_REVIEW_REQUIRED` |
| CVE-2026-78408 | Same nine util-linux packages | Trixie vulnerable; `nsenter --join-cgroup` descriptor/credential behavior. Image contains `nsenter`; app does not invoke it. Debian lists a forky/sid fix. | `HUMAN_SECURITY_REVIEW_REQUIRED` |
| CVE-2026-78409 | Same nine util-linux packages | Trixie vulnerable; `X-mount.subdir` path resolution issue. Current tracker pages show differing source fixed-version metadata (2.42.3-1 vs release row 2.42.4-1); verify vendor packaging before remediation. | `HUMAN_SECURITY_REVIEW_REQUIRED` |
| CVE-2026-78410 | Same nine util-linux packages | Trixie vulnerable; restricted bind-mount source replacement issue. Current tracker pages show differing source fixed-version metadata; verify vendor packaging before remediation. | `HUMAN_SECURITY_REVIEW_REQUIRED` |
| CVE-2025-69720 | `libncursesw6`, `libtinfo6`, `ncurses-base`, `ncurses-bin`; `6.5+20250216-2` | Trixie vulnerable; overflow in `infocmp`. `/usr/bin/infocmp` exists in image but app does not call it. Debian labels Trixie `no-dsa`; forky/sid versions are fixed. | `HUMAN_SECURITY_REVIEW_REQUIRED` |
| CVE-2026-16742 | `libsystemd0`, `libudev1`; `257.13-1~deb13u1` | Trixie vulnerable; systemd-homed local privilege escalation. The image has shared libraries, not a running systemd-homed service. | `HUMAN_SECURITY_REVIEW_REQUIRED` |
| CVE-2026-54369 | `libacl1`; `2.3.2-2+b1` | Trixie vulnerable; pathname ACL symlink traversal. The library is present; app code does not call ACL pathname APIs. Debian says no Trixie DSA/backport because the fix changes ABI. | `HUMAN_SECURITY_REVIEW_REQUIRED` |
| CVE-2026-9538 | `perl-base`; `5.40.1-6+deb13u1` | Trixie vulnerable/postponed; Archive::Tar attacker-controlled size allocation. `perl-base`/`/usr/bin/perl` are present, while `Archive::Tar` was absent in the inspected image. | `HUMAN_SECURITY_REVIEW_REQUIRED` |

The CVE descriptions and current Trixie/forky/sid status were checked against the [Debian Security Tracker](https://security-tracker.debian.org/tracker/). In particular, Debian marks the listed Trixie versions vulnerable; `no-dsa`/`postponed` are Debian dispositions, not this project's acceptance. No unstable/unsupported base migration, untested package removal, suppression, or waiver was made. **Do not call the image clean or release-ready.** Next safe step is a human-reviewed, compatibility-tested image/package remediation followed by a fresh scan of a source-identified image.

## 4. SSRF and egress boundary

The current unit tests validate configuration-time URL parsing/allowlist behavior and Provider client configuration. Code inspection confirms `httpx.AsyncClient(..., trust_env=False)`, no opt-in to redirects, and default TLS verification. The URL validator rejects non-HTTPS production URLs, userinfo, malformed/ambiguous numeric IP representations and disallowed/private/local addresses at configuration load.

This does not pin the resolved address to the eventual socket peer and does not prove resistance to DNS rebinding, compromised DNS, proxy/network-route changes or a redirect from an alternate client path. The checked Kubernetes `NetworkPolicy` includes a permissive namespace-wide egress selector, so it is not evidence of a restrictive provider-only egress boundary. The gateway's diagnostic Compose network was Docker-internal, but that is not a Kubernetes egress test.

Fresh command: `python -m pytest -q tests/unit/test_config_and_registry.py tests/unit/test_openai_compatible_provider.py tests/unit/test_openai_compatible_provider_contract.py` — **33 passed, exit 0**. DNS-rebinding/IPv6 test matrix, TLS error test, redirect-to-private target, socket-peer assertion, and positive/negative Kubernetes NetworkPolicy egress probes were not executed; these remain **BLOCKED / NOT PROVEN**, not PASS.

## 5. Remaining release gates

- **FAILED:** security acceptance for the identified image until a human approves a defensible disposition/remediation for all 44 High matches and a rebuilt image is rescanned.
- **FAILED:** capacity objective at concurrency 32 and 64 due to controlled overload responses; define production SLOs and investigate queue/admission sizing/DB round trips before claiming capacity.
- **BLOCKED:** historical 1,984/1,984 503 root cause; required failure-time evidence did not exist.
- **BLOCKED:** full SSRF/DNS rebinding and restrictive runtime egress controls.
- **PASS (narrow):** PostgreSQL SIGKILL/restart with unchanged synthetic state, small synthetic custom-format dump/restore, and Redis SIGKILL/recovery behavior. **NOT RUN:** full production-scale database backup/restore; replica/HA behavior (no HA claim); old-new-old schema/image compatibility; repeatable migration plus upgrade/rollback; end-to-end Prometheus/OTel/Jaeger/alert delivery; complete SSE fault matrix. Soak was intentionally withheld because c=32/c=64 capacity acceptance failed.
- **NOT RUN:** fresh Trivy scan of a source-identifiable image built from current HEAD `0acc85e`; the scanned image is from `3a06d06`.

Release status remains **NOT READY**. No release tag, production deployment or availability/HA guarantee follows from this report.

## 6. Reproduction and source references

- Evidence files use the external root listed above and contain synthetic identifiers only; do not upload raw environment/configuration files without reviewing them for credentials.
- The original check-pointed image and scan results remain under `E:\project-test-assets\01-gateway\results\production-hardening-wave2-20261011T045752Z\03-docker-reproducibility`.
- Official tracker references: [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642), [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408), [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409), [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410), [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720), [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742), [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369), and [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538).
