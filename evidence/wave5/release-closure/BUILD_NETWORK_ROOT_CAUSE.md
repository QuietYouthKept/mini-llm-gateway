# Build Network Root Cause — Wave 5.1

Status: PARTIAL — recovered, historical cause unproven.

## Evidence

The user identified the workstation HTTP proxy as `http://127.0.0.1:7892`. A later live check confirmed the listener, then tested each relevant hop without disabling TLS validation:

| Hop | Evidence | Result |
|---|---|---|
| Windows host → PyPI | explicit-proxy HTTPS GET/HEAD | HTTP 200 |
| Docker Engine container → host proxy | `host.docker.internal:7892` | HTTP 200 |
| BuildKit RUN → host proxy | predefined proxy build args; `host.docker.internal:7892` | HTTP 200; exit 0 |
| Clean final builds → public package source | two independent no-cache builds | both exit 0 |

Earlier direct network probes also succeeded. Therefore the historical TLS EOF was not reproduced and cannot be attributed conclusively to the proxy, PyPI, BuildKit, or a dependency. Docker Desktop also reported its own proxy endpoint (`http.docker.internal:3128`), so the effective proxy route differed by execution context. No proxy credentials were passed or persisted.

## Changes and limits

The Dockerfile now installs only locked production dependencies before application sources are copied (`uv sync --no-install-project`). The runtime source is copied directly and imports successfully. A second change removed compile-time bytecode generation after the strict comparison isolated nondeterministic `.pyc` bytes.

The successful rebuild is evidence of recovery, not proof of the original TLS root cause. Future release builds should record proxy settings as redacted metadata and retain the actual BuildKit log. TLS verification remained enabled; no `trusted-host`, insecure index, or embedded credential was used.
