# ADR-0001: Clean (Hexagonal) Architecture

- Status: Accepted
- Date: 2026-08-14

## Context

The gateway must let business code talk to many model providers (mock, OpenAI,
DeepSeek, self-hosted) behind one API, while keeping governance logic — routing,
fallback, budgets, audit — testable in isolation.

A naive single-module FastAPI app would mix HTTP parsing, provider calls, and
business rules, making it hard to test governance independently of a provider
or a running server.

## Decision

Use Clean Architecture with four layers:

- domain — models, ports, domain errors (no framework imports)
- application — use cases and services (routing, fallback, budgets, guardrails)
- infrastructure — providers, SQLite, config, metrics
- interfaces/http — routes, schemas, auth, middleware, error handlers

The composition root (app/core/container.py) wires concrete adapters into a
single AppContainer. The domain depends on nothing; outer layers depend inward.

## Consequences

- Governance logic (ChatService, FallbackService, budget, guardrails) is
  unit-testable without HTTP or a real provider.
- Swapping mock providers for real ones is a config + adapter change, not a
  rewrite of routing/fallback.
- More files and indirection than a monolithic module — accepted because the
  gateway's value is exactly this separation of concerns.
