# Interview guide

## 30-second introduction

mini-llm-gateway is an explainable LLM control plane: one OpenAI-compatible
endpoint applies authentication, governance, routing, fallback, budgets, audit,
and evidence-oriented failure tests around providers.

## Two-minute architecture

FastAPI owns request context and auth; `ChatService` owns the governed request
state machine. Provider adapters sit behind a port. SQLite is the local
durable default, PostgreSQL provides shared budget/audit state, Redis supplies
global rate limit, shared exact cache, and a TTL lease for global cold-miss
coalescing. Metrics and prompt-free traces form the operations boundary.

## Engineering stories

1. **Cache governance bypass:** cache only post-guardrail output and include a
   policy fingerprint in the key; regression tests prove a stale policy does
   not serve unsafe output.
2. **Budget TOCTOU:** reserve atomically before provider work, then settle or
   release exactly once; the state row makes invalid transitions observable.
3. **Replica state ownership:** Redis owns global limiter/cache/singleflight;
   PostgreSQL owns audit and budget; circuit breakers remain intentionally local.
4. **Offline replay safety:** replay is data-driven and provider-free unless a
   caller explicitly opts in to a live call.
5. **Failure evidence:** deterministic public-data fixtures and fault providers
   distinguish expected policy failures from unexplained 5xx responses.

## Common follow-ups

- **Why Redis for rate limiting and PostgreSQL for budgets?** Limiting needs a
  cheap atomic window; budgets need durable transactional accounting.
- **Why are circuits local?** They protect a process from immediate cascading
  failure without imposing a globally synchronized health authority.
- **Why not LiteLLM directly?** The project demonstrates the ownership,
  invariants, tests, and operating evidence behind a gateway, not adapter count.
- **What happens if a singleflight leader dies?** The lease expires; followers
  poll with bounded backoff and recompute only after ownership is available.
