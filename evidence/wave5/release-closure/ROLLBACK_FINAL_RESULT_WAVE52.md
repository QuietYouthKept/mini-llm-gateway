# Wave 5.2 rollback result

Status: **PASS** for the tested old→new→old application/schema/API sequence.

In isolated Compose project `wave52-rollback`, the old candidate `c4ba57dafd380ca1d1a6ba39b40de0732d30a697` (`sha256:9c85…`) started against fresh PostgreSQL 16, applied/verified the seven-entry migration ledger, and served Readiness, Chat, and SSE. The new candidate `5a474c208d3095e678469f307a7c7d549233e6b9` (`sha256:44486…`) then used the same PostgreSQL and Redis state and passed the same checks. Rolling back to the old candidate again passed all checks.

The captured final database state contains nine request logs, six settled reservations, six stream finalizations, and six provider attempts; every reservation has a matching finalization, with no duplicate finalization key. `git diff c4ba57d..5a474c2 -- app migrations` was empty, so application and migration sources were identical across these two tested images; the tested container difference was image/build provenance, not an application schema change.

An initial harness assertion looked for `[DONE]`; the actual Gateway contract emits the terminal SSE event `event: done`. The original response was preserved, the check was corrected to the real contract, and all three phases passed. Pure deployment transition time was not independently instrumented; the evidence-file timestamp gaps are not reported as deployment latency.

See `UPGRADE_ROLLBACK_MATRIX_WAVE52.json` and the request/SSE/DB evidence under `wave52-rollback/`.
