# Container Build and Runtime Report

## Runtime staging

The local image `mini-llm-gateway:wave5-cmd-fix-fcd3bce` built and ran in an isolated Wave 5 staging stack. Its default image command was exercised without a Compose command override after changing the Dockerfile to `python -m uvicorn`.

Observed: Linux/amd64; runtime user `10001:10001`; read-only root filesystem; all Linux capabilities dropped; `no-new-privileges`; `/app` writes fail with `EROFS`; the configured `/tmp` tmpfs is writable. Healthcheck was healthy. `/live` and `/ready` both reached HTTP 200 after the readiness recovery window; synthetic chat and TCP SSE returned HTTP 200. PostgreSQL migration ledger contained seven rows. SIGTERM produced exit code 0 and logged application shutdown completion. This does not constitute a full upgrade/rollback drill.

The app-only image manifest/config digest from that runtime build was `sha256:a9590563079e89c57e82e61495e476d2274b3d1a8502fe23afedd711ae164948`. It is a local experimental build from a dirty worktree, not a registry-published release image or a clean committed build.

## Reproducibility attempt

The first cached build completed. A second independent no-cache build used the same local context, platform, Dockerfile, base-image digest, lockfile, `VCS_REF`, and fixed `BUILD_DATE`, but failed at the locked `uv==0.11.23` installation because the build container's connection to PyPI ended with `SSLEOFError: UNEXPECTED_EOF_WHILE_READING`. The exit code was 1. TLS verification was not disabled and no insecure mirror was added.

Therefore no valid pair of completed builds exists, and rootfs/layer/config/manifest equality could not be compared. Strict reproducibility is **FAILED / NOT VERIFIED**, not passed. Evidence is in `final-gates/docker-build-compose.log` and `final-gates/repro-build-2.log`.

## Image security scan

Docker Scout v1.18.3 generated a local SBOM successfully. `docker scout cves` in Markdown and SARIF format and `docker scout recommendations` each returned exit code 1 with a request to authenticate. This current scan is BLOCKED; no current CVE count or security pass is claimed. The local image did not have a registry RepoDigest; its local image/config identifier must not be described as a published registry digest.

Separately, pip-audit 2.9.0 audited a hash-pinned requirements export from `uv.lock` for the development and production extras. It reported no known vulnerabilities and exited 0. This covers locked Python distributions, not Debian OS packages or the whole image.
