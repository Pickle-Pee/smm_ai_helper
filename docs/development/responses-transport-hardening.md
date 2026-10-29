# Responses transport hardening

Based on origin/master a51a12d and the 2026-10-29 Responses audit. This change
covers legacy transport defects only; provider representation, business output
validation, quality gates, persistence and durable graph retry policy are unchanged.

## Response acceptance

Every 2xx response passes the same `_single_attempt_output` barrier, including
responses to a repeated HTTP request. Only explicit `status=completed` with
nonempty text is accepted. Incomplete responses (even with text), refusal
blocks, malformed JSON/envelopes and explicitly unfinished message items fail
with the existing bounded `ModelResponseError` enum. Refusal inspection precedes
the convenience `output_text` shortcut. The accepted return shape remains
`(str, dict)`; application JSON/schema/semantic validation still owns its checks.
A provider omitting the completion status now fails closed.

The [Responses API reference](https://developers.openai.com/api/reference/python/resources/responses)
distinguishes completed and incomplete response states. No live API requests
are needed to verify the local acceptance policy.

## Local POST budget

There is one send loop. Legacy calls use
`min(3, max(1, HTTP_RETRIES + 1))` POSTs at most. Every POST preserves the initial
clamped `max_output_tokens` and `text.format`; the multiplier and output-retry
branch are removed. The maximum sum of requested legacy output allowances is
therefore `3 * MAX_OUTPUT_TOKENS_CAP` (12000 with current configuration), not a
monetary or input-token cost guarantee.

Only HTTP 429/500/502/503/504 responses may trigger bounded local backoff.
The existing exact HTTP 400 `temperature` / `unsupported_value` compatibility
policy may remove temperature once and consumes an ordinary send slot.
No HTTP 400 schema error removes `text.format`, and no fallback changes
Structured Outputs. Transport errors, timeouts, HTTP 408, cancellation, invalid
JSON and rejected envelopes do not repeat locally. The final HTTP failure
propagates as `HTTPStatusError`; network failures propagate as their existing
HTTPX/timeout types rather than a generic exhausted-retries wrapper.

Graph mode still makes exactly one POST, with its existing server-owned
`ModuleOutputBudget` (including 16000-token profiles). Its worker classifier,
three durable attempts, 5s/10s backoff, leases and fencing are unchanged.
Confirmed empty anomalies still retry only through the durable owner in graph
mode. Legacy no longer retries that anomaly locally. Higher-level fixed workflow
retries retain their existing policy; this PR cannot guarantee one external
execution across those durable attempts.

## Usage and diagnostic receipts

The existing `_post_response` telemetry emits a separate started/finished receipt
and `provider_call_id` for every actual POST, including HTTP rejection, model
rejection, cancellation and transport failure. Existing schema fingerprints,
provider IDs, graph correlation and redaction stay in the same telemetry stream.
No second telemetry store or adapter is introduced.

`usage_state` and scalar states preserve missing/null/invalid/reported values.
Reported integer zero remains distinct from missing or unavailable; it never
proves absence of charges. `billing_outcome=unknown` makes that limitation
explicit. `outcome_unknown=true` marks absence of an observed HTTP response or
HTTP 408. `response_received`, HTTP status and the existing outcome label keep
known HTTP errors separate from a lost response.

For compatibility the returned dictionary contains only the accepted response's
usage (or `{}` when unavailable). It is **not** an aggregate cost receipt. Usage
from earlier responses is retained in their individual telemetry records and
must not be silently treated as zero when absent. This PR adds no billing ledger
or persistence migration and does not establish actual provider charges.

## Offline evidence

`tests/test_responses_transport_hardening.py` uses `httpx.MockTransport`, inspects
serialized POST bodies and forbids real socket connections. On Windows the
internal asyncio socketpair is constructed before the network guard. Cases
cover ordinary and strict success, first/second-attempt incomplete/refusal/invalid
responses, schema HTTP 400, caps and send exhaustion, temperature compatibility,
two different usage receipts, missing versus zero usage, invalid JSON, timeout,
transport loss and HTTP 408. A second attempt is reached through a known HTTP
error, since a first incomplete envelope now terminates immediately.

Existing telemetry/graph/model-budget suites verify graph single-POST behavior,
server-owned profiles, exception classification, worker cancellation, redaction
and successful legacy workflow use. No local PostgreSQL, Redis, Docker,
production service or paid provider request is part of these checks.
