# Candidate Image Security Report — Wave 5.1

Status: FAILED release security gate; no risk exception approved.

Target: `mini-llm-gateway:wave51-candidate-c4ba57d`, OCI image `sha256:9c85a88dba65c3e7ac1493690ea1fe9198821284021df8eca92f0267a3e600fb`, source `c4ba57dafd380ca1d1a6ba39b40de0732d30a697`.

Scanner: Trivy 0.75.0, vulnerability database v2, `UpdatedAt=2026-10-09T19:06:47Z`, downloaded at `2026-10-10T01:56:58Z`. Full JSON: `trivy-image-scan-final.json`; raw output: `trivy-image-scan-final.log`; scanner exit: 0 (scan completed, which is not a statement that vulnerabilities are acceptable).

Findings: 334 package-level vulnerability findings across Debian 13.6 and Python dependencies: 3 Critical, 88 High, 144 Medium, 96 Low, 3 Unknown. The current CISA KEV feed was fetched through the user-designated proxy and matched 0 CVE IDs. This does not establish non-exploitability or remove the Critical/High release blocker. Fixable-version metadata is included in `CVE-TRIAGE-MATRIX.json`.

Docker Scout SBOM generation succeeded earlier, but all Scout CVE/SARIF/recommendation commands were blocked by Docker ID authentication. No password or token was requested. The local Trivy scan is the authoritative current scan for this candidate; the historical Scout failures are retained in `scout-cves-*.log` and `scout-exit-status.json`.

No Critical/High has been manually classified as fixed or not affected; no reviewer risk acceptance exists. The release candidate is therefore **not accepted**. Do not deploy this image to production until the Critical/High findings are remediated or independently assessed and explicitly accepted through the project’s security process. Base-image comparison was not run, so this report makes no before/after reduction claim.
