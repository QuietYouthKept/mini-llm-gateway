# API property and OpenAPI contract results

## Hypothesis

The bounded seeded probe made 15 actual HTTP requests against a local TCP Gateway: 8 Unicode/valid values returned 200, 2 boolean numeric values returned 422, and 5 overlong values returned 400. All eight successful requests were individually checked for persisted audit, receipt, and settled reservation. The result file contains aggregate counts only; it omits prompt values and request IDs.

## Schemathesis

Schemathesis 4.30.1 ran against only `POST /v1/chat` and `POST /v1/chat/completions`, with seed 20261012 and bounded fuzzing. It generated 127 cases; all 127 passed. The run found contract mismatches during earlier iterations (undocumented common errors, SSE content shape and booleans accepted as numeric values). Those failures are retained; after the OpenAPI and strict numeric request-model fixes, the final run passed. This is a bounded generated run, not exhaustive API verification.

## Source changes

The Chat schemas now reject Python booleans where integer/float values are expected. OpenAPI documents the common HTTP error response codes and the SSE JSON event envelope used by the runtime. Tests assert those schema contracts and boolean rejection on both Chat routes.

## Evidence

See external `reports/hypothesis-api-result.json`, `reports/schemathesis-final.log`, `reports/schemathesis-final-junit.xml`, and the retained failed iterations. `.schemathesis/` is a local tool cache and is deliberately excluded from source commits.
