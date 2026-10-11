# Current-source image security scan and restricted runtime

Date: 2026-10-11\
Source: `3a06d06198757f1eeb306b7d8d2e0d46e842df25`\
Image/config identity: `sha256:eb587db5331fdd4f13bd579344a38a8c2839c5c98f42b9f47a4ff31f561b70d2`\
Evidence root: `E:\project-test-assets\01-gateway\results\production-hardening-wave2-20261011T045752Z\03-docker-reproducibility`

## Scanner and SBOM

The final scan used Trivy v0.75.0 from the official [`aquasecurity/trivy` release](https://github.com/aquasecurity/trivy/releases/tag/v0.75.0). The Windows x64 ZIP SHA-256 (`4e43bd71a30f51aee39525f60f2b47043af77eb8df8fe082aae4372b69c6660f`) matched the official release checksum list before extraction. Vulnerability database download completed at `2026-10-11T05:36:05Z`. The Docker Hub pull of the scanner container returned EOF; the checksum-verified native binary then accessed the Docker Desktop named pipe and scanned the locally loaded exact OCI candidate. TLS verification remained enabled and proxy port 7890 was used for outbound downloads. A preceding v0.74.0 scan is retained as an earlier experiment and returned the same severity counts; v0.75.0 is the reported current result.

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

The 44 High entries are package/CVE matches, not 44 unique CVEs: they collapse to 8 distinct CVE identifiers across 17 package records. The four `util-linux` CVEs appear against multiple binary/runtime packages; the other findings affect `acl`, `ncurses`, `systemd`, and Perl's `Archive::Tar`. Debian's Security Tracker currently marks the image's Debian 13/Trixie versions vulnerable for the checked examples: [`CVE-2026-76642`](https://security-tracker.debian.org/tracker/CVE-2026-76642), [`CVE-2026-78408`](https://security-tracker.debian.org/tracker/CVE-2026-78408), [`CVE-2026-78409`](https://security-tracker.debian.org/tracker/CVE-2026-78409), [`CVE-2026-78410`](https://security-tracker.debian.org/tracker/CVE-2026-78410), [`CVE-2026-54369`](https://security-tracker.debian.org/tracker/CVE-2026-54369), [`CVE-2025-69720`](https://security-tracker.debian.org/tracker/CVE-2025-69720), [`CVE-2026-16742`](https://security-tracker.debian.org/tracker/CVE-2026-16742), and [`CVE-2026-9538`](https://security-tracker.debian.org/tracker/CVE-2026-9538). Trivy reports no fixed version for the detected packages. Debian notes such as `no-dsa` or `postponed` are upstream distribution dispositions, not approval to accept this project's risk. Runtime hardening (non-root, dropped capabilities, read-only filesystem) reduces some attack surface, but does not substitute for a project-owned disposition or patched rebuild.

## Container runtime checks

The exact candidate image was run as UID/GID `10001:10001`, with a read-only root filesystem, all Linux capabilities dropped, and `no-new-privileges`. Temporary writable mounts were limited to `/tmp` and `/app/data`.

- `/app` write as the application user: denied (expected).
- `/tmp` and `/app/data` temporary writes: succeeded.
- `/live`: HTTP 200; Docker health status: `healthy`.
- `docker stop --timeout 10`: successful; container exit code 0.

This was an isolated local SQLite smoke. It does not satisfy PostgreSQL/Redis staging, migration repeatability, upgrade/rollback, dependency recovery, backup/restore, or production readiness.

## Evidence files

- Final scanner: `candidate-trivy-0.75-vuln.json`, `candidate-trivy-0.75-vuln.log`, `candidate-trivy-0.75-vuln.exitcode`
- Final SBOM: `candidate-sbom-0.75.cdx.json`, `candidate-sbom-0.75.log`, `candidate-sbom-0.75.exitcode`
- Final summary: `candidate-scan-summary-0.75.json`
- Earlier v0.74.0 scanner output and SBOM remain preserved as separate files.
- Runtime: `candidate-runtime-check.json`, `candidate-runtime.log`, `readonly-permission-probe-verified.json`
- Tool provenance: `trivy_0.75.0_checksums.txt`, `trivy_0.75.0_windows-64bit.zip`, `trivy-latest-release-api.json` (plus the retained v0.74.0 provenance)
