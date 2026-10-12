# Interview deep dive

## Why a real TCP fault test?

Mocking an exception does not prove which bytes/events reached a client before a connection reset. The scenario uses a local Gateway, a synthetic OpenAI-compatible provider and Toxiproxy. It waits until the client parses three actual SSE message events, then installs a downstream `reset_peer` toxic. A delayed fourth provider frame causes the toxic to act. The observable contract is checked at both sides: client sees three messages followed by an error (never `done`); Provider B is not called after output has begun; the SQLite request audit, provider attempt and reservation finalization agree.

## Why keep failure evidence?

The first version stalled without sending another frame and produced a timeout rather than a reset. That is a different failure mode. Preserving it prevents us from relabeling a timeout as a network reset and shows why a delayed trigger frame is needed. The final passing case and the failed attempt are separate artifacts.

## Why property tests and Schemathesis?

The Hypothesis probe generates bounded input classes and makes per-success persistence assertions, not just status-code assertions. Schemathesis checks generated requests against the published OpenAPI contract. Its earlier failures found contract drift: undocumented common errors, SSE event envelope shape, and Python booleans passing numeric validation. Strict request fields and response schemas were updated, then the bounded final generation run passed.

## What remains outside the evidence?

PostgreSQL and Redis integrations were not run; SQLite cannot prove their locking or distributed semantics. Performance and Docker release gates were resource-blocked or historical failures. A strong answer explicitly separates local correctness evidence from production readiness.
