# Docker image reproducibility: measured root cause and scoped result

Date: 2026-10-11\
Source: `3a06d06198757f1eeb306b7d8d2e0d46e842df25`\
Evidence root: `E:\project-test-assets\01-gateway\results\production-hardening-wave2-20261011T045752Z\03-docker-reproducibility`

## Finding

The earlier no-cache image builds did not have identical root filesystems. The investigation compared the actual saved layer tar members, not just image IDs:

- Layers 1–5 were byte-identical.
- Layer 6 contained generated `/etc` account files whose only differing metadata was `mtime` (including passwd/group/shadow and subordinate ID files).
- Layer 7 contained 2,061 `.venv` entries. Content hashes, mode, ownership and symlink metadata matched; only entry `mtime` differed.
- Layers 8–10 differed only in directory mtimes under `/app` and `/app/migrations`.

Thus, timestamp metadata in generated `RUN`/`COPY` layers is the observed cause for the original mismatch. This finding does not claim every potential nondeterminism has been eliminated.

## Reproducibility experiment

Two clean, independent, no-cache Linux/amd64 Buildx exports used the same committed context, source epoch, proxy and exporter options:

```text
docker buildx build --no-cache --platform linux/amd64 --provenance=false --sbom=false \
  --build-arg SOURCE_DATE_EPOCH=1791695795 \
  --build-arg HTTP_PROXY=http://host.docker.internal:7890 \
  --build-arg HTTPS_PROXY=http://host.docker.internal:7890 \
  --output type=oci,dest=<independent-archive>,rewrite-timestamp=true .
```

BuildKit documents `SOURCE_DATE_EPOCH` and timestamp rewriting on the OCI exporter as reproducibility mechanisms; the option is applied at export time and does not change application source or Dockerfile behavior ([BuildKit reproducible builds](https://github.com/moby/buildkit/blob/master/docs/build-repro.md)).

Both builds succeeded and generated 61,011,456-byte archives with SHA-256 `1946fbc7ed4ef7574efddd4eaa23e837137720d84027a6a15842a5ff31f255f7`. A separate parser then verified equality of the OCI index, manifest, config, all ten layer descriptors, and all ten rootfs diff IDs. OCI index digest: `sha256:0b4db23b99fcb8709870689940b1bc38baa4f27ab25baa8735a6f57629415c74`; manifest digest: `sha256:eb587db5331fdd4f13bd579344a38a8c2839c5c98f42b9f47a4ff31f561b70d2`.

## Gate interpretation

**PASS, narrowly scoped:** two independent OCI exports from this source commit, platform, Buildx command, build inputs and timestamp-rewrite option were identical at both archive and OCI object levels.

This does not establish that default `docker build`, other platforms, altered dependencies, changed base images, or future builds are reproducible. The earlier differing images remain valid historical experiment results. No release tag or production-ready claim follows from this check.

## Evidence files

- `candidate-build-1.oci.tar`, `candidate-build-2.oci.tar`
- `candidate-build-1.identity.json`, `candidate-build-2.identity.json`
- `candidate-build-1.command.txt`, `candidate-build-2.command.txt`, exit-code files
- `candidate-oci-identity-comparison.json`
- `prior-layer-comparison.json`, `prior-42935410.docker-save.tar`, `prior-e208f0.docker-save.tar`
