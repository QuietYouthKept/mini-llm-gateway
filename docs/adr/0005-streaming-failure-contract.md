# ADR-0005: Streaming failure contract

## Status

Accepted.

## Context

Streaming has a different failure boundary from a buffered request.  Once an
SSE `message` event is sent, a gateway cannot safely retry or switch providers:
doing so could duplicate content and cost.  The former implementation selected
only the first routed provider, so its behavior also differed from the
non-streaming fallback policy before any content was delivered.

## Decision

For a streaming request, admission (authentication, rate limit, profile,
input policy, and budget reservation) completes before the HTTP response is
started. Any admission failure after the reservation is created follows the
same atomic release-and-audit finalization path. The gateway then follows this
contract:

1. Before the first non-empty `message` event, it tries routed candidates in
   priority order. When fallback is disabled, only the first candidate is
   considered. When fallback is enabled, missing providers and open circuits
   are operational skips and always advance to the next candidate;
   `fallback.trigger_on` governs failures returned by providers (timeout,
   provider failure, and bad status). The whole-request deadline still bounds
   the chain.
2. Each stream candidate gets one connection attempt.  We deliberately do not
   retry a streaming handshake in place: an upstream may have accepted work
   even when the client cannot prove whether it did.  Selection across the
   profile's fallback chain is the bounded recovery mechanism.
3. When the first non-empty chunk has been emitted, the provider is pinned.
   The gateway never transparently retries or falls back.  It emits exactly
   one SSE `error` event with `{code, message, request_id}` if the stream then
   fails.
4. Streaming responses are never served from or written to the exact cache.
   Cancellation and partial output settle observed/estimated usage; failures
   that exhaust selection without invoking a provider release the reservation.
   Reservation transition, request audit, attempt audit, and a unique
   finalization receipt commit in one database transaction. A commit whose
   result is unknown is queried by receipt and otherwise left for
   reconciliation; it is never blindly retried as a different operation.
5. Audit status is one of `completed`, `cancelled`, `provider_error`,
   `partial_provider_error`, `guardrail_blocked`, or
   `partial_guardrail_blocked`; a deterministically rejected settlement is
   recorded as `accounting_failed` with no fabricated usage or budget. The
   request trace records observed character
   and estimated-token counts, settlement source, and every provider attempt.
6. Provider usage is trusted only when it is a complete, internally consistent
   set of non-negative integers. Missing usage is estimated; partial,
   malformed, negative, oversized, or conflicting counters use a non-negative
   bounded local estimate with `usage_source=estimated_invalid_provider_usage`.
   The gateway never records a negative token or cost debit.
7. The HTTP response owns the prepared stream session. Closing an ASGI body
   before its first iteration, failure while sending response headers, and a
   normal body shutdown all call `StreamingSession.aclose()`. This makes an
   unstarted reservation terminal rather than relying on an async-generator
   `finally` that may never run.

## Consequences

This gives callers an unambiguous recovery boundary: they may receive a normal
stream, or an SSE error after headers are committed.  Consumers must use the
request ID to inspect the audit record when an SSE error is received.  It also
means stream availability can differ from buffered availability after the
first token, by design.

Provider URL allowlists and literal-IP checks are configuration-time defenses.
They do not pin DNS results and do not replace runtime DNS rebinding controls,
network egress policy, or an outbound proxy/firewall.

The persisted reservation state machine is `reserved -> settled` or
`reserved -> released`; both terminal states are immutable. `uncertain` is an
application outcome classification, not a guessed database state. On a lost
commit acknowledgement the gateway reads the receipt by reservation ID and
accepts it only when request ID, operation, and payload fingerprint match. If
that cannot be proven, the row is left untouched for query/reconciliation.

Lease reconciliation is also a terminal persistence path. For an expired
`reserved` row it atomically writes an `orphaned_released` request audit and a
zero-usage `release` receipt before committing the release. It does not invent
provider usage for a process that crashed before finalization; the audit has
`reservation_lease_expired` and `usage_source=not_billed` so operations can
distinguish it from a provider-settled stream.
