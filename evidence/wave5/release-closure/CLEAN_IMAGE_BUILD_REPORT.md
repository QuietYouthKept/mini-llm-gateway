# Clean Image Build Report — Wave 5.1

Status: PASS for two-build local reproducibility; not a release acceptance because image security gates fail.

- Source commit: `c4ba57dafd380ca1d1a6ba39b40de0732d30a697`
- Git tree: `7cfffb2c5b4bed00d530e432d43ab419861fba68`
- Dockerfile SHA-256: `eb26ce109784e657d8895665cb9f86c5e4c421b70c6c911528afb97568b6dded`
- uv.lock SHA-256: `76be330260e5a6f204c866d344eddb1fac96a07fd513e1a74b5496c0e6c9c5bf`
- Base: Python 3.12.14 / Debian 13.6, pinned manifest `sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65`
- Platform/tooling: `linux/amd64`, BuildKit 0.23.2, buildx 0.27.0-desktop.1
- Build method: clean source commit, two independent `--no-cache` BuildKit exports, OCI output with timestamp rewriting, provenance and embedded SBOM disabled for the deterministic comparison.
- Build logs: `candidate-c4ba57d-build-1.log`, `candidate-c4ba57d-build-2.log`; both completed successfully.
- Both OCI archives: 60,738,048 bytes, SHA-256 `679f9eebeb1c4672e5967dbb0289ac2af28a2e7efed09d0afc68d701226b0a3b`.
- OCI manifest/index digest: `sha256:9c85a88dba65c3e7ac1493690ea1fe9198821284021df8eca92f0267a3e600fb`.
- Image config digest: `sha256:2c6a69e40ebb020a4cc3e10f23dacf1c13fc3ca3cc28f931850cf569c3af3d83`.
- Nine RootFS DiffIDs and nine layer digests matched across builds; exact comparison is in `REPRODUCIBILITY_COMPARISON.json`.
- Runtime imports passed for FastAPI, psycopg and redis. Compose runtime verified UID/GID `10001:10001`, read-only rootfs, all capabilities dropped, and `no-new-privileges`.

The image was loaded from an OCI archive into the local Docker engine. Its displayed SHA is an OCI manifest/image identifier, **not** a registry-published RepoDigest. No image was published.
