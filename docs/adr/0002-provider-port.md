# ADR-0002: ProviderPort abstraction + registry

- Status: Accepted
- Date: 2026-08-14

## Context

Business code historically scattered provider-specific if-else logic. The
gateway needs one uniform way to call providers and react to their failures,
regardless of whether a provider is a mock or a real HTTP API.

## Decision

Define a single ProviderPort interface (async chat(...)) that every provider
implements. Providers signal failures with typed domain errors:

- ProviderTimeoutError
- ProviderFailedError
- ProviderBadStatusError

A provider registry (build_provider_registry) maps config type -> adapter
instance. Fallback/retry/circuit-breaker logic consumes the port and the typed
errors, never provider-specific details.

## Consequences

- Adding a provider (e.g. OpenAICompatibleProvider) is one adapter class plus a
  config entry; the routing/fallback engine is untouched.
- Fault-injection mocks and real providers are interchangeable, enabling the
  demo and eval harness without real API keys.
- Provider-specific fields (usage tokens, finish_reason) are normalized at the
  adapter boundary into a common ChatResponse shape.
