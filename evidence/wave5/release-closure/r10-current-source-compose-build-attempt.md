# Current-source Compose-triggered build attempt

Date: 2026-10-10 (local time). This attempt did not produce an image and is not a completed build gate.

- Command: `docker compose -p wave52-r10-iter1 -f deploy/wave5/compose.yaml -f evidence/wave5/release-closure/r10-compose-resource-limits.yaml up -d --force-recreate gateway`
- Source present in the host app bind mount: `c9ddbe65f94f460a55cad07fe78c5e6b061f6dc4`.
- Compose first failed to pull its default `mini-llm-gateway:wave5-local` reference (`registry-1.docker.io` EOF), then invoked BuildKit from the current Dockerfile.
- Base image metadata resolved. BuildKit failed while pip attempted pinned `uv==0.11.23`, emitting repeated TLS `UNEXPECTED_EOF_WHILE_READING` messages for `/simple/uv/`.
- The attempt was interrupted after repeated identical TLS EOF retries; no exit status was captured, no candidate image was produced, and the certificate verification setting was not changed.
- Existing running diagnostic gateway remained on its original local image and read-only host app mount. It was subsequently restarted and `/live` and `/ready` returned 200.

This is additional failure evidence only; do not count it as a successful build or as either of the two complete A/B reproducibility builds.
