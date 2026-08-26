# Security policy

## Supported version

Security fixes target the current `1.0.0-rc1` line until a stable release is
published.

## Reporting

Do not open a public issue with exploit details or credentials. Use the
repository's private security-advisory channel when enabled; otherwise contact
the repository owner through its public profile and request a private channel.

## Boundaries

The checked-in keys are synthetic local-demo credentials, not production
secrets. Production deployments must terminate TLS at an ingress/proxy, store
provider and admin credentials in a secret manager, restrict `/admin` and
`/metrics`, and use TLS-authenticated PostgreSQL/Redis connections. Request
bodies and replay payloads remain opt-in because they may contain sensitive
content.
