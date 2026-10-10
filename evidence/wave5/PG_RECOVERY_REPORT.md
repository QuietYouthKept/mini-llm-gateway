# PostgreSQL Recovery Report

The isolated probe uses PostgreSQL 16, Redis 7, the local Linux/amd64 gateway image, and an isolated project-scoped network. It repeats an abrupt PostgreSQL SIGKILL at concurrency 20 and 50, then starts PostgreSQL and waits for the application readiness endpoint to recover before checking persisted request rows and reservation states.

All six fault rounds passed the defined outage oracle. During the outage, every generated chat request returned HTTP 503 classified as `database_unavailable`; no audit or reservation rows were found for those request IDs. `/ready` returned HTTP 503 under 0.8 seconds and `/live` returned HTTP 200 under 32 ms. On PostgreSQL restart, the script observed readiness recovery and queried the database before proceeding to the next round.

This is evidence for fail-closed behavior before a budget reservation is durably created. It is not evidence that writes already submitted to PostgreSQL are known committed or rolled back after a lost acknowledgement. Commit-unknown receipt reconciliation, process death during settlement, and SIGTERM during a live stream remain unverified.

Raw evidence: `evidence/wave5/pg-outage-p1-isolated-repeat3.json`. The earlier two probe files remain preserved but are invalid because their projects shared an explicitly named Docker network.
