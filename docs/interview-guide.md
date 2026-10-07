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

## Five-minute walkthrough

Start at HTTP: middleware creates a request ID and auth resolves a client. The
service applies rate, profile, and input policy before checking only governed
cache values. A local event collapses in-process misses; Redis can add a
deployment-wide TTL lease. Before a provider call, the gateway reserves budget.
Routing then attempts providers under one deadline with retry/fallback and local
circuit breakers. Output policy runs before cache publication; settlement and
request/attempt audit create the durable evidence. The important design point is
that every mutable state has an owner and a failure semantic.

## Engineering stories

### 1. Cache governance bypass

**Problem:** a raw provider result could be cached before policy, letting future
hits bypass a changed rule. **Invariant:** only governed output keyed by policy
fingerprint is reusable. **Design:** guardrail before cache put; policy version
in cache key. **Evidence:** cache/guardrail tests. **Tradeoff:** exact cache has
low reuse versus semantic cache, but its governance contract is inspectable.

### 2. Budget TOCTOU

**Problem:** check-then-increment admits concurrent calls past quota.
**Invariant:** admitted usage plus active reservations never exceeds limit.
**Design:** DB-bound reserve, then one settle or release state transition.
**Evidence:** race demo and state-machine tests. **Tradeoff:** a conservative
reservation can reject work that would later consume fewer tokens.

### 3. Process-local versus distributed state

**Problem:** a process-local limiter/cache makes each replica independently
admit work. **Design:** Redis owns global rate/cache/singleflight; PostgreSQL
owns durable budget/audit; circuit stays local deliberately. **Evidence:**
two-replica probes. **Tradeoff:** shared dependencies add availability modes.

### 4. Distributed singleflight

**Problem:** a shared cache alone does not prevent a cold-miss stampede.
**Invariant:** an old owner cannot delete a successor's lock. **Design:** unique
token, `SET NX PX`, Lua compare/delete, bounded follower polling, TTL recovery.
**Evidence:** one provider execution and stale-owner recovery probe. **Tradeoff:**
Redis outage degrades to local coalescing, not a global guarantee.

### 5. Replay safety

**Problem:** a live replay can bill providers or cause side effects.
**Invariant:** default replay must make no provider call. **Design:** offline
decision replay with live mode explicit. **Evidence:** replay tests. **Tradeoff:**
offline replay validates decisions, not provider behavior.

### 6. Evidence-driven engineering

**Problem:** happy-path unit tests miss integration ownership and failure modes.
**Design:** deterministic WildChat/UltraChat corpus, fault providers, response,
DB, metric, and trace oracles. **Evidence:** test cards and load report.
**Tradeoff:** workstation evidence is not a capacity certification.

## Deep-dive questions

- **Why Redis for rate limiting and PostgreSQL for budgets?** Limiting needs a
  cheap atomic window; budgets need durable transactional accounting.
- **Why are circuits local?** They protect a process from immediate cascading
  failure without imposing a globally synchronized health authority.
- **Why not LiteLLM directly?** The project demonstrates the ownership,
  invariants, tests, and operating evidence behind a gateway, not adapter count.
- **What happens if a singleflight leader dies?** The lease expires; followers
  poll with bounded backoff and recompute only after ownership is available.
- **Why cache fail-open but limit fail-closed?** A cache miss costs latency;
  admitting unlimited work during loss defeats a governance control.
- **Why does a distributed lock need an owner token?** A stale worker must never
  delete the lease acquired by a newer worker after expiry.
- **Why do reservations expire?** A process crash cannot retain quota forever;
  the derived lease remains longer than the request deadline.
- **Why cannot OTel replace a decision trace?** Traces are operational telemetry;
  the audit trace records explainable policy and routing decisions.
- **Why retain SQLite?** It provides a dependency-light, durable local/demo path
  while PostgreSQL is the shared production adapter.
- **What if PostgreSQL fails over?** Budget/audit fail closed; deployment needs
  a managed failover, retry, and backup policy not claimed by this project.
