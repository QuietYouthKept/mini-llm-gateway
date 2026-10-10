# Wave 5.1 Execution Checkpoint

- Current Git HEAD before report packaging: `c4ba57dafd380ca1d1a6ba39b40de0732d30a697`; branch `codex/wave51-release-closure`.
- Untouched original worktrees: `D:\面试\github-projects\mini-llm-gateway` and `D:\面试\github-projects\mini-llm-gateway-wave5`.
- New work/evidence root: `E:\mini-llm-gateway-wave51`.
- Candidate image: `mini-llm-gateway:wave51-candidate-c4ba57d`; OCI ID/manifest `sha256:9c85a88dba65c3e7ac1493690ea1fe9198821284021df8eca92f0267a3e600fb`.
- Compose project: `wave51-release-closure`; port 18151.
- Passed gates: two identical clean builds; Ruff; compileall; 204 passed/1 skipped; 81.08% branch coverage/80% threshold; security eval 8/8; Provider Contract 13; TCP SSE 2; PostgreSQL probe; Redis probe; same-version graceful SIGTERM/restart.
- Failed/unproven gates: Critical/High image CVEs; actual TCP Commit Unknown; old/new rollback; end-to-end OTel and Prometheus query; DNS/redirect egress; repeated fair performance matrix; historical TLS EOF root cause.
- Latest fully executed DB probe: `scripts.postgres_integration_probe.py --database-url postgresql://gateway:***@postgres:5432/gateway` inside isolated Compose network; exit 0.
- Latest scan: Trivy 0.75.0, refreshed DB, full image JSON; exit 0 but release policy fails on 3 Critical/88 High.
- Next command: inspect and package the named evidence files, run `git diff --check`, then stage only the two Dockerfile commits already present and explicitly selected report/evidence files; do not stage OCI archives, coverage HTML, cache or all of `evidence/`.
- Remote push: normal SSH 443 push succeeded. GitHub CI run `38015606740` passed for `de6d2a3e0d8a4a0b61afc75fbfe16d2c4beceda3`; 205 passed, branch coverage 84.02%, independent 80% gate passed. Evidence Artifact `11656405425`; validation Artifact `11656695290`; independently checked 155/155 hashes with 0 mismatches (manifest `850ac4938b1594821c101e93ca817b6b293c1dbf56fabf2e56986a0004a37db8`).
- Tag: none.
