# Current-source image security scan and restricted runtime

Date: 2026-10-11\
Source: `3a06d06198757f1eeb306b7d8d2e0d46e842df25`\
Image/config identity: `sha256:eb587db5331fdd4f13bd579344a38a8c2839c5c98f42b9f47a4ff31f561b70d2`\
Evidence root: `E:\project-test-assets\01-gateway\results\production-hardening-wave2-20261011T045752Z\03-docker-reproducibility`

## Scanner and SBOM

Trivy v0.74.0 was obtained from the official `aquasecurity/trivy` GitHub release. The Windows x64 ZIP SHA-256 (`94c40e0696e4b907a74b7b2e1438d5d72ebaca83115817407f568a002d520842`) matched the official release checksum list before extraction. Vulnerability database download completed during the scan. The Docker Hub pull of the scanner container returned EOF; the checksum-verified native binary then accessed the Docker Desktop named pipe and scanned the locally loaded exact OCI candidate. TLS verification remained enabled and proxy port 7890 was used for outbound downloads.

Results for this scan:

| Severity | Count |
| --- | ---: |
| Critical | 0 |
| High | 44 |
| Medium | 63 |
| Low | 62 |
| Unknown | 3 |
| **Total** | **172** |

Trivy detected 87 Debian OS packages and 40 Python packages (127 total detected packages). A CycloneDX 1.7 SBOM was generated with 128 components. These are time- and scanner-version-bound results, not a claim of zero vulnerabilities. The image security release gate is **FAILED** until the High findings are triaged and addressed or formally dispositioned, then rescanned.

## Container runtime checks

The exact candidate image was run as UID/GID `10001:10001`, with a read-only root filesystem, all Linux capabilities dropped, and `no-new-privileges`. Temporary writable mounts were limited to `/tmp` and `/app/data`.

- `/app` write as the application user: denied (expected).
- `/tmp` and `/app/data` temporary writes: succeeded.
- `/live`: HTTP 200; Docker health status: `healthy`.
- `docker stop --timeout 10`: successful; container exit code 0.

This was an isolated local SQLite smoke. It does not satisfy PostgreSQL/Redis staging, migration repeatability, upgrade/rollback, dependency recovery, backup/restore, or production readiness.

## Evidence files

- Scanner: `candidate-trivy-vuln.json`, `candidate-trivy-vuln.log`, `candidate-trivy-vuln.exitcode`
- SBOM: `candidate-sbom.cdx.json`, `candidate-sbom.log`, `candidate-sbom.exitcode`
- Summary: `candidate-scan-summary.json`
- Runtime: `candidate-runtime-check.json`, `candidate-runtime.log`, `readonly-permission-probe-verified.json`
- Tool provenance: `trivy_0.74.0_checksums.txt`, `trivy_0.74.0_windows-64bit.zip`, `trivy-release-v0.74.0-api.json`
