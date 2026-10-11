# Wave 2 production hardening baseline

## Captured identity

- Capture time: 2026-10-11 04:58:21 UTC
- Branch: `codex/p0-p1-production-hardening`
- HEAD: `4d067cc2bdd137218ad055e15bfaf85b1078644f`
- HEAD tree: `e6112a8b5b161cd632f6216799959c443ab1b42d`
- Initial commit tree recorded before this wave: `e6112a8b5b161cd632f6216799959c443ab1b42d`
- External checkpoint: `E:\project-test-assets\01-gateway\results\production-hardening-wave2-20261011T045752Z\00-checkpoint`
- Prior evidence root remains untouched: `E:\project-test-assets\01-gateway\results\production-hardening-20261011T021712Z`

## Current local delta (uncommitted at capture)

Tracked modifications: `app/application/services/blocking_io.py`, `app/application/services/chat_service.py`, `app/domain/errors.py`, and `tests/unit/test_blocking_io.py`.

Untracked files: `docs/production-hardening/00_BASELINE_AND_SCOPE.md`, `docs/production-hardening/01_POSTGRES_LOCK_TIMEOUT_FINDING.md`, `docs/production-hardening/EXECUTION_CHECKPOINT.md`, and `scripts/postgres_live_contention_probe.py`.

The exact binary tracked diff, copied untracked files and SHA-256 manifest are in the external checkpoint. The captured working-tree delta is not part of HEAD and must not be described as remotely validated.

## Build inputs and host

- `uv.lock` SHA-256: `76be330260e5a6f204c866d344eddb1fac96a07fd513e1a74b5496c0e9c5bf`
- `Dockerfile` SHA-256: `7924312e44711c135dbc22d78c264cd223d8760bf4a44fa929c82189d1d14d73`
- `docker-compose.yml` SHA-256: `0d74c458330aa615c090ff2a6aa5b7c9ab27b394daa84531d36e799d46243a5c`
- Windows 11 build 26200; PowerShell 7.6.5; `uv 0.11.23`; Docker Desktop engine 28.3.3; Buildx 0.27.0; BuildKit v0.23.2; Docker context `desktop-linux`; Docker reports 24 CPUs and 16,351,653,888 bytes RAM.
- System `python` on PATH is Python 3.8.3 and is below the project's supported version; use the project-managed `uv` environment and record its actual interpreter version for tests.
- User-confirmed proxy port 7890 accepts TCP on `127.0.0.1`; the prior Docker build proxy address was `host.docker.internal:7890`. TLS verification must remain enabled.
- Existing disposable project `gw-prod-hardening-20261011t021712` is running with Gateway, PostgreSQL 16 and Redis 7. Unrelated containers were not changed.
- Candidate image tag `mini-llm-gateway:ph-lock-timeout-final-4d067cc` has image ID `sha256:42935410d1bee19ec864c038b092091f1c9b9f94673deae5f30491aafcad4072`; this image is based on uncommitted source and is not a commit-bound release artifact.

## Inherited evidence boundaries

- The injected PostgreSQL advisory-lock test confirmed `55P03` must be request-scoped; the initial tracked fix is not yet committed or remotely verified.
- The candidate had local tests and isolated PostgreSQL/Redis probes recorded in the previous evidence root. Those outcomes are prior-run evidence, not this run's rerun.
- Docker no-cache repeatability previously failed (`429354…` vs `e208f0…`); exact cause is unknown. The candidate image CVE count and SBOM are unknown; prior Scout scan was blocked by login and no local Trivy/Grype/Syft was available.
- Historical 1,984/1,984 HTTP 503 root cause remains unconfirmed. Do not rerun the formal 36-cell matrix until correctness and accounting invariants permit it.

## Protected workspaces and prohibited operations

This run is confined to `E:\mini-llm-gateway-prod-hardening` and its new external evidence directory. Do not modify the dataset-evaluation, resume-impact, Wave 51, or original D-drive workspaces. Do not reset, clean, force-push, merge Main, create a production tag, deploy, change unrelated containers/volumes, use production secrets, or call a paid provider.
