# Responses provider correlation

The authoritative path is `app.worker` -> `ModuleGraphWorker` -> dispatcher /
module executor -> `production_model_call` -> `openai_text.chat(single_attempt=True)`.
`GraphExecutionService.claim` commits the incremented `JobExecution.attempts` and
fencing lease before any external work. No database transaction spans provider I/O.

## Internal telemetry contract: llm_provider_request.v1

Every existing Responses POST passes through `_post_response`, which emits one
`event=started` record immediately before the HTTP invocation and one
`event=finished` record on return, rejection, transport failure or cancellation.
The same UUID `provider_call_id` joins these records. Fields are structured logging
extras **and** content-free key/value messages so the existing production formatter
retains them. Started/success events use INFO; other finished outcomes use WARNING. A rejected
envelope extends the existing `Structured model response rejected` record; there
is no second rejection event or duplicate diagnostics implementation.

| Fields | Meaning / bounds |
| --- | --- |
| telemetry_version, event | Closed version and started/finished labels |
| request_mode | single_attempt or legacy; selects the caller's existing output policy |
| provider_call_id | Locally generated UUID hex for each HTTP invocation |
| correlation_state | graph or unbound |
| job_id, run_id, node_id, module_id, module_execution_id | Task-local graph identity, labels capped at 128 ASCII characters |
| plan_revision, graph_attempt | Positive integers from the runtime claim (attempt is the committed JobExecution counter) |
| graph_attempt_id | SHA-256 of the fencing claim token; raw capability is never logged |
| model, max_output_tokens | Selected request configuration; bounded model label, existing budget |
| schema_fingerprint | SHA-256 of UTF-8 schema JSON with sorted keys and compact separators; null without a schema |
| http_status, response_received | HTTP status or null when unavailable; whether a buffered response was received |
| x_request_id, response_id | Only recognized bounded req_/UUID and resp_ IDs; absent when unavailable or malformed |
| response_status | completed/incomplete/failed/in_progress/queued/cancelled; unknown/invalid/unavailable otherwise |
| incomplete_reason | max_output_tokens/content_filter/other or null; never raw provider text |
| duration_ms | Monotonic duration of the observed invocation including envelope inspection, capped at 2^31-1 ms |
| outcome | success/rejected/retry_requested/http_error/transport_error/timeout/cancelled |
| reason | Existing closed ModelResponseFailureReason, for rejected envelopes only |
| usage_state | missing/null/present/invalid; unavailable without an observed response |
| input_tokens_state, output_tokens_state, total_tokens_state, reasoning_tokens_state | missing/null/reported/invalid |
| input_tokens, output_tokens, total_tokens, reasoning_tokens | Present only when reported as nonnegative integers; zero is an explicit reported value |
| output_tokens_details_state | missing/null/present/invalid for the nested usage container |

Input/total counters are capped at 2^31-1; output is capped at the selected budget;
reasoning is capped at valid output usage (otherwise the budget). Booleans, floats,
strings and oversized values are invalid. A missing nested scalar is distinct from
a null nested container through its container-state field. Existing rejected-response
byte lengths and bounded output-item diagnostics remain (only the first 32 item
labels are inspected); no item content or IDs are logged.

`outcome` describes this individual POST under `request_mode`, not the aggregate
chat invocation. `single_attempt` success means the envelope passed the existing
strict Responses parser. `legacy` success means the existing text extractor accepts
the text and this response takes the return path: this includes incomplete/content_filter
with nonempty output_text and completed envelopes with output_text plus output=null.
Legacy's first-response empty/max_output_tokens predicate is shared with the caller;
its existing output retry is recorded as `retry_requested`. The expansion response
uses the existing nonempty-text check, which can accept incomplete/max_output_tokens
with text. A later fallback/retry can therefore succeed after an earlier non-success
POST. Observation neither triggers retries nor changes acceptance policy.
`http_error` covers every non-2xx response (including 302), matching HTTPX
raise_for_status; redirects remain unfollowed. Only the caller owns HTTP errors,
fallbacks and retries. Invalid JSON/envelope diagnostics remain bounded.

Executor JSON/schema/provenance checks, quality gates and fenced artifact commit
happen later; this event does not establish graph success. A started event proves
local invocation, not provider receipt. Abrupt process death can leave it without
a finished event. When transport fails before a response is available, provider
IDs/status/usage are unknown rather than invented. Durable log retention/export is
an operational prerequisite for historical correlation; this PR adds no new store.

## Ownership, isolation and compatibility

The immutable graph context is installed around dispatch in a ContextVar and reset
in finally, including errors and cancellation. Concurrent tasks cannot overwrite
one another. Attempts for the same module execution have different claim digests;
module_execution_id remains the existing Job ID. The outer asyncio.Timeout handle
identifies deadline cancellation as timeout; shutdown cancellation stays cancelled
and leaves the lease recoverable. The persisted attempt counter and existing retry
owner/policy are unchanged: single_attempt still issues one POST, and the durable
runtime retains three attempts with the existing 5/10 second deferred backoff.

The classifiers `incomplete_empty_max_output_tokens` and
`incomplete_max_output_tokens` are unchanged. Only the confirmed empty anomaly
remains retryable. Ordinary budget exhaustion remains terminal.

Other existing chat callers have `correlation_state=unbound`: they have no graph
execution, so no graph identity is fabricated. Their existing retry/fallback POSTs
are also individually observed. GraphWorkItem gains an in-memory attempt field
(default 1 preserves construction compatibility); it is not persisted or exposed
in public DTOs. No migration, public response change, dependency, model, token
budget, new provider POST, deployment or retry-policy change is introduced.

Only these allowlisted fields are logged. API keys, Authorization, prompts,
system instructions, schema text, user content, raw bodies and exception messages
never enter the telemetry. Sentinel tests inspect rendered logs and LogRecord
fields, not just message text.

## Verification

Deterministic MockTransport tests exercise success, empty incomplete, HTTP failure,
transport failure, HTTP and worker timeout, cancellation, concurrent attempts,
context reset, usage presence/zero semantics, provider-ID rejection and redaction.
Existing production worker PostgreSQL/Redis tests additionally verify three deferred
durable retries, one unchanged POST per attempt and committed claim correlation.
Concurrent successful production executions are matched to their persisted jobs,
leases and accepted artifacts.
