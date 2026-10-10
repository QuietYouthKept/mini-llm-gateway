# Network Egress Acceptance

Status: PARTIAL / NOT ACCEPTED.

Proxy plumbing is verified: host, Docker Engine and BuildKit container reached PyPI over TLS through the user-indicated `http://127.0.0.1:7892` / `host.docker.internal:7892` path and received HTTP 200. This validates the route, not the application’s provider egress policy.

Not run against a live provider adapter: DNS rebinding between validation and connect, redirect to loopback/private/metadata, IPv6 private targets, proxy bypass, and internal Redis/PostgreSQL target attempts. Configuration-time URL validation must not be treated as runtime DNS pinning or egress firewalling. No claim is made that a DNS-resolved address remains the connected address. Production-style network egress remains a release blocker until connection pinning/egress policy is experimentally verified.
