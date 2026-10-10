# Final Evidence Index

Evidence is preserved under `evidence/wave5/release-closure/`; large raw OCI archives, Trivy JSON, run outputs, and downloaded GitHub artifacts remain untracked and are intentionally not cleaned. Never infer a current-source image result from source `5a474c2`.

## Source and CI

| Evidence | What it proves | Identity / result |
| --- | --- | --- |
| Iteration 1 code commit `4febd225a1e5fc1144cda0f4596a5af16242c2a9` | Initial bounded finalization lane and overload classification | Branch `codex/wave51-release-closure`; tree `b260fa10a57bf080464f9ef34b66db05f95aebac`. |
| Current code commit `c9ddbe65f94f460a55cad07fe78c5e6b061f6dc4` | Cancellation/generic-error recovery routing through finalization lane | Current tree `322a6116f590cdaf55cad07fe78c5e6b061f6dc4`. |
| [GitHub Run 38031469583](https://github.com/QuietYouthKept/mini-llm-gateway/actions/runs/38031469583) | Latest verified CI on docs snapshot `60cc10e` containing unchanged source `c9ddbe6` | 208 passed, 83.47% pytest-only branch coverage; independent coverage gate passed. |
| Evidence Artifact `11662094179` | Public sanitized CI evidence ZIP | Uploaded, 155 manifest files; validated by the workflow. |
| Validation Artifact `11661634786` | GitHub manifest validation result | Validator passed; no mismatch reported. |
| Manifest hash | Identity of the latest CI manifest | `372b73aa37a29a159c5f1e17f496298c8dc1eb4f2757eadd1c1f4455c4916856`. |

The uploaded archive contains JUnit, pytest-only coverage XML/HTML and gate output, PostgreSQL/Redis integration results and module coverage, Redis two-replica, HTTP/SSE, Provider Contract, Functional/Security Eval, Secret Scan, Dependency Audit, environment versions, exit statuses, and a manifest. For Run 38031469583, the workflow downloaded the uploaded ZIP and its validator passed before publishing the validation artifact; older local rehash records remain tied to their own historical run.

## R10 reliability and performance

- Root-cause/fix analysis: `R10_ROOT_CAUSE_AND_FIX.md`.
- Before/after machine summary: `R10_BEFORE_AFTER_BENCHMARK.json` (only populated for cells with raw completed runs).
- Final verification and pending gates: `R10_FINAL_VERIFICATION.md`.
- Previous failed valid-format matrix: `WAVE52_PERFORMANCE_RERUN_REPORT.md`, `wave52-performance-rerun/formal-summary.csv`, and `wave52-performance-rerun/final-formal/` (old source, no resource quotas).
- New matched-resource baseline run directories: `r10-iter1-baseline/` (old source image).
- New-source diagnostic run directories: `r10-iter1-source/` (source c9dd `app/` mounted read-only on previous dependency image; not a built-image gate).
- Completed before/after summary: `R10_BEFORE_AFTER_BENCHMARK.json`; actual DB snapshots precede reconciliation; no reconciliation was run.
- Compose cap declarations: `r10-compose-baseline-limits.yaml`, `r10-compose-resource-limits.yaml`.
- DB invariant snapshots and per-project metrics are to be captured before reconciliation under unique names next to their run directories.

## Candidate/image/build security

- Prior candidate provenance/reproducibility: `FINAL_CANDIDATE_PROVENANCE_WAVE52.json`; source 5a image ID `sha256:44486db8bb69095129d72cb1303937df117d968ffae703b8e3055a021fd5dacf`.
- Prior image vulnerability results: `trivy-wave52-candidate-5a474c2.json` (0 Critical / 44 High; R04 failed).
- Current source BuildKit failure attempts: `r10-candidate-4febd22-build-a.log`, `.exitcode`, `r10-candidate-4febd22-build-b.log`, `.exitcode` (TLS EOF, each exit 1).
- No current-source image, SBOM, reproducibility comparison, or current-source image scan exists yet.

## Historical release-gate evidence

- Existing Wave 5.2 summary: `WAVE52_FINAL_CLOSURE.md`.
- Original machine-readable gate snapshot: `RELEASE_GATES_WAVE52.json`.
- New current status: `RELEASE_GATES_FINAL.json`.
- PostgreSQL outage (20/50 SIGKILL, six runs): `wave52-pg-outage-probe.json` (source 5a; repeat required for current image).
- Upgrade/rollback pair `c4ba57d → 5a474c2 → c4ba57d`: `UPGRADE_ROLLBACK_MATRIX_WAVE52.json`, `ROLLBACK_FINAL_RESULT_WAVE52.md` (that exact pair only).
- Dependency Security report: `IMAGE_SECURITY_REPORT.md`; OTel partial: `OBSERVABILITY_RUNTIME_REPORT.md`; egress partial: `NETWORK_EGRESS_ACCEPTANCE.md`; wire-level Commit Unknown: `COMMIT_UNKNOWN_WIRE_LEVEL_REPORT.md`.

## Current conclusions

`R10_GATE=FAILED`, `ENGINEERING_FREEZE_READY=false`, `RELEASE_READY=false`. R04 remains FAILED; R06 NOT EXECUTED; R08/R09 PARTIAL. R10's after-source measured accounting is improved, but c32/64 admission rejection remains and there is no current-source image. No tag, merge, or production deployment is recorded. See `FINAL_ENGINEERING_HANDOFF.md` for next steps and `docs/POST_FREEZE_PRODUCTION_BACKLOG.md` for bounded deferred work.
