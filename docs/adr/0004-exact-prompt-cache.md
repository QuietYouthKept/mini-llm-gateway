# ADR-0004: Exact-match prompt cache first

- Status: Accepted
- Date: 2026-08-15

## Context

AI Gateway products (Cloudflare, Portkey, LiteLLM, Helicone) treat caching as a
first-class lever for latency and cost. The gateway is the natural place to put
it because it already sees every request and every response.

## Decision

Implement an in-memory exact-match prompt cache, not semantic cache:

- Cache key = SHA-256 of the canonical request (profile + messages + params).
- The key also includes an output-policy fingerprint, and cached responses are
  immutable copies of the post-guardrail response.
- TTL + LRU eviction, bounded by max_entries.
- A cache hit skips the provider call AND the budget charge entirely; it records
  cache_hit, cache_key, and an estimated cost-saved amount in the audit log and
  metrics.

Semantic caching is explicitly deferred: it introduces embeddings, similarity
thresholds, and false-hit risk, which would distract from the gateway's core
governance story at this stage.

## Consequences

- Deterministic, easy to reason about, and safe (exact match only).
- Demonstrates a cost-optimization story without cloud API keys.
- The cache is in-memory and per-process — documented as a known limitation; a
  distributed cache (Redis) would slot in behind the same PromptCache interface.
- Singleflight coalesces identical misses only within one process; it is not a
  distributed lock and does not prevent duplicate calls across replicas.
