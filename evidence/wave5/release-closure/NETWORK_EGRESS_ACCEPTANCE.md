# Network Egress Acceptance

Status: PARTIAL / NOT ACCEPTED (Wave 5.2 update).

Proxy plumbing is verified: the Windows host reached Docker Hub (HTTP 200), Docker Registry (HTTP 401, expected unauthenticated response), and PyPI (HTTP 200) through `http://127.0.0.1:7897`. The Docker Engine/BuildKit route through `host.docker.internal:7897` reached PyPI over TLS and completed a real locked-wheel download (exit 0). The user-confirmed active proxy port is 7897; no 7892 route is used by this Wave 5.2 verification. This validates the route, not the application’s provider egress policy.

Not run against a live provider adapter: DNS rebinding between validation and connect, redirect to loopback/private/metadata, IPv6 private targets, proxy bypass, and internal Redis/PostgreSQL target attempts. Configuration-time URL validation must not be treated as runtime DNS pinning or egress firewalling. No claim is made that a DNS-resolved address remains the connected address. Production-style network egress remains a release blocker until connection pinning/egress policy is experimentally verified.
