# Wave 4 Container Report

## Result: PARTIAL; deployment acceptance FAILED

- Existing Wave 3 Dockerfile, Compose and staging changes were preserved and reviewed; no further rootfs reproducibility iteration was attempted this Wave.
- Local image build succeeded from pinned Python base digest `sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f`. The Wave 4 image came from a dirty tree and carries HEAD label `d8d8d2d`; it is not a commit-reproducible release image.
- Local image SBOM: `image-sbom.cdx.json`, 177 packages. Current image vulnerability scan was blocked because Docker Scout required Docker login (`image-cves.exitcode` nonzero). No current-image CVE count is claimed.
- Historical Wave 3 scan found 44 High / 58 Medium / 61 Low / 3 Unknown / 0 Critical on an older image only. These historical counts do not apply to current image.
- Container smoke passed for UID/GID 10001, read-only root filesystem, read-only config mounts, writable `/tmp` tmpfs, app-path write denial, health check, migration idempotency and SIGTERM stream shutdown.
- PostgreSQL/Redis normal staging and SSE smoke passed; concurrent PostgreSQL outage failed latency/readiness acceptance. Redis failure handling returned classified 503, but readiness exceeded the harness deadline.
- Rollback to existing `wave2-rc1` image returned a functional request but readiness 503; rollback acceptance **failed**.
- Strict reproducibility: prior Wave 3 independent builds matched only 5 of 10 rootfs layers. Status remains `REPRODUCIBILITY_FAILED`; no complete Image Config/Manifest reproducibility proof exists.
- Upgrade/rollback did not meet release criteria. No data-destructive migration rollback was attempted.
- Runtime egress/DNS rebinding/redirect SSRF enforcement was not tested; configuration URL validation is not an egress boundary. Status: `NETWORK_EGRESS_NOT_VERIFIED`.

Evidence: `staging-acceptance-final.json`, `image-sbom.cdx.json`, `image-cves.exitcode`, and preserved Wave 3 container evidence under `../wave3/`.
