# Responses workflow diagnostics

This runbook describes the Responses execution chain after PR #135 and the opt-in
workflow governor. Provider, JSON Schema, business validation and Quality Gates
are unchanged. PostgreSQL owns execution state; logs are observations rather than
an exactly-once billing ledger.

## Execution and ownership

```text
Telegram CopilotClient -> POST /copilot/execute -> CopilotAPIService
 -> optional owned-site extraction + intent interpretation
 -> MarketingCopilotService -> deterministic planner / compiler
 -> GraphExecutionService.start_compiled_run -> PostgreSQL MarketingRun / Jobs
 -> Redis hint OR PostgreSQL due scan -> ModuleGraphWorker
 -> ModuleExecutorDispatcher -> executor -> production_model_call
 -> app.llm.openai_text.chat(single_attempt=True) -> Responses API
 -> completed-envelope barrier -> executor business validation -> Quality Gates
 -> fenced artifact + Job completion + dependent scheduling transaction
 -> owner-scoped GET run -> Telegram rendering
```

The graph has no automatic Telegram delivery queue: the bot reads accepted run
artifacts. The retained fixed marketing_mvp.v1 lane uses MarketingExecutors,
separate Jobs and WorkflowDelivery parts. Its artifact, completion and delivery
parts commit atomically; delivery retries do not invoke generation.

The transport owns at most one graph POST per adapter invocation; the durable
worker/service own graph attempts and backoff. Executors and dispatcher do not
retry or repair. The legacy Responses transport allows
`L = min(3, max(1, HTTP_RETRIES + 1))` POSTs per chat invocation, including the
narrow unsupported-temperature compatibility send. Its local retries accept
429/500/502/503/504, never HTTP 408, timeout or lost transport. The transport uses
httpx directly, with no additional SDK retry loop.

## Maximum sends and requested allowance

Defaults below are upper bounds, not guaranteed traffic and **not monetary cost
estimates**. A successful attempt can consume input, output and reasoning tokens;
a failed or lost response may also incur charges. Only provider records establish
actual charges. Each claim consumes one of three graph attempts, including a
crash before any POST. A blocked executor can make zero POSTs.

| Scenario | Nodes | Maximum graph Responses POSTs | Sum of requested max_output_tokens |
| --- | ---: | ---: | ---: |
| Explicit single generic module | 1 | 3 | 12,000 |
| Explicit single POSITIONING / VIRTUAL_CMO / EXPERIMENTS | 1 | 3 | 48,000 |
| competitive_positioning_v1 | 2 | 6 | 60,000 |
| strategy_builder_v1 without research | 3 | 9 | 144,000 |
| strategy_builder_v1 with market and 3 competitors | 7 | 21 | 192,000 |
| strategy_builder_v1 with r research nodes (0..4) | 3+r | 9+3r | 144,000+12,000r |

The three strategy synthesis modules have 16,000-token profiles; research and
CREATOR use 4,000. These bounds apply to current approved production bindings and
three attempts per node. Governed sends additionally cannot exceed the
snapshotted run call cap and aggregate allowance; a smaller allowance may
terminate a run earlier. Unknown outcomes stop that node conservatively.

Pre-run API work is outside the graph budget: one execute invocation can add one
intent call and, when requested, one owned-site extraction call. Each uses the
single-attempt adapter. Persisted interpretations and owned snapshots allow reuse,
but concurrent misses and crashes before saving can repeat provider work. Thus a
full seven-node request within one API invocation permits 23 Responses POSTs when
both pre-run calls occur. Their generic allowances add at most 8,000, yielding
200,000 requested tokens. Repeated user submissions/new request keys have no
global billing bound.

| Retained path, defaults | Upper bound | Scope / remaining exposure |
| --- | --- | --- |
| Fixed analysis | 3 claims x L = 9 Responses POSTs; 36,000 allowance | URL extraction parses pages locally |
| Fixed creative | 3 x 2 x L = 18 Responses POSTs; 49,500 allowance | Each claim can repeat 4,000-token creative generation and 1,500-token image brief |
| Fixed mentor | 3 x L = 9 Responses POSTs; 36,000 allowance | Explicit continuation required |
| Full fixed three-step run | 36 Responses POSTs; 121,500 allowance | Image generation is additional |
| Fixed creative images | Up to 3 x (HTTP_RETRIES+2) = 12 generation POSTs | Verification rejection may precede fallback retries; default HTTP_RETRIES=2, one variant, forced template; cache may reduce calls |
| Delivery | Up to 8 sends per part per delivery cycle | Zero model calls; explicit delivery retry resets counter |
| Synchronous Copilot module | At most one module POST per execute invocation | Pre-run calls additional; repeated HTTP submissions have no durable module result replay |
| Legacy chat / standalone tasks | L per chat invocation | Multiple generation/QC/facts/image stages, outside graph governor |

Fixed workflows, chat, standalone tasks and image generation retain existing
outer retry policies. This governor covers durable graph Responses calls, not a
universal account-spend limit. Do not apply graph maxima to those paths.

## Timeouts and recovery

| Boundary | Default | Meaning |
| --- | ---: | --- |
| Copilot bot HTTP | 310s wall, 300s HTTP phases, 10s connect | No automatic bot retry; user may retry |
| Legacy bot/backend HTTP | 10s phases | Separate existing path |
| Copilot API execute | 300s wall | Acquisition / interpretation / synchronous dispatch / start |
| Responses HTTP | 60s per httpx phase | Not a total workflow deadline |
| Graph execution | 300s wall | Includes executor/source/provider work |
| Graph lease | 330s | Must exceed execution timeout |
| Fixed execution / lease | 240s / 270s | Three claims, 5s then 10s deferred backoff |
| Public source fetch | 25s wall / 10s phases | At most four redirects; no LLM |
| Delivery lease | 90s | Independent of generation |

Settings enforce `0 < HTTP_TIMEOUT < GRAPH_TIMEOUT_SECONDS < GRAPH_LEASE_SECONDS`.
The graph deadline does not include every later persistence operation. Database
outage propagates and retains the lease. Neither timeout nor cancellation proves
that provider execution stopped.

Claims lock admission first, then graph run, execution lease and Job. Claim count,
available_at and fencing token live in JobExecution. WorkerAttempt tracks
in-flight work for drain control, not provider receipts. Completion checks current
token, live lease, run and routing identity. Artifact, Job completion and dependent
scheduling are atomic. Redis loss does not lose canonical work. Cancellation
propagates without a domain failure; cleanup removes only that attempt's marker.
The lease permits later recovery. Fencing prevents stale database writes, not
external effects.

An old run can repeat provider work after timeout, HTTP 408, crash, cancellation
or completion-persistence failure. A governed run reserves before HTTP and retains
a receipt; an unresolved reservation prevents another send on the same node after
restart. A crash between reservation and POST can consume allowance even if no
request reached the provider. See the retry policy for conservative stopping.

## Correlation and safe logs

Reuse llm_provider_request.v1 started/finished receipts and GraphCallContext;
there is no second logging sink. Correlate job_id, run_id, node_id,
module_execution_id, graph_attempt_id, provider_call_id, request_id, response_id,
model, schema_fingerprint, max_output_tokens, status, incomplete_reason,
usage_state, input_tokens, output_tokens, reasoning_tokens, duration_ms,
retry_owner and retry_decision. Existing x_request_id and response_status names
remain available. A graph attempt ID is a one-way digest of its claim token;
never log the fencing capability itself.

Provider IDs and model labels are bounded/validated. Schema fingerprint is a
SHA-256 digest of canonical schema JSON. Full schemas, user text, credentials,
request/response bodies, HTTP exception messages and arbitrary headers are
excluded. Input byte lengths are metadata, not content.

The additive token_usage_state and input_tokens_usage_state / output_tokens_usage_state /
reasoning_tokens_usage_state fields normalize counter states; usage_state keeps its
existing v1 envelope-presence meaning. Workflow decision records use
usage_state=not_applicable. Keep reported_zero, missing, unknown and
not_applicable separate. A reported zero
is a provider counter; missing is absent data; unknown means no established
outcome/counter; not_applicable means the measurement does not apply. None of
these states means execution was free. Older receipts have legacy states such as present, reported,
null, invalid and unavailable; analysis preserves uncertainty instead of turning
absent usage into zero.

## Historical read-only analysis

```powershell
python scripts/analyze_responses_logs.py worker.log worker-previous.log
python scripts/analyze_responses_logs.py --help
```

The CLI reads local plain key=value logs or JSONL and prints aggregate JSON. It
imports no app/provider client, requires no API key and performs no network calls.
Supply files chronologically. Use complete logs from all worker replicas,
including restarts and rotations.

The report includes provider call count, attempts, success/failure, anomaly
frequency, problematic logical requests, module distribution, known/unknown token
usage and repeated calls after an unknown outcome. Started/finished observations
are deduplicated by provider_call_id. A started-only call is unknown, never a
confirmed failure or charge. Rejection-only legacy logs are counted separately,
without inventing a call or usage.

Missing correlation prevents exact attempt counts and problem-request
denominators. Missing rotations, mixed clocks and partial windows limit ordering
and replay detection. A rate over observed correlated runs is not a population
incident rate. Provider success is not business acceptance, delivery or proof of
billing. This PR supplies an instrument; no complete historical input dataset was
supplied, so it does not establish historical incident statistics.
