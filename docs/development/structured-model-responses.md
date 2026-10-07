# Structured model responses after PR #102

Base: master `6250d75b92becfe2d5196274d0d186abaf0d835b`.
The reported production `ModelResponseError` proves a rejected 2xx envelope;
it does not establish the historical provider reason. HTTP schema rejection
occurs earlier and remains `httpx.HTTPStatusError`. No historical response or
production provider call was recovered or captured for this change.

## Ownership and diagnostics

`ModuleGraphWorker` restores a durable JobExecution, dispatches its exact module
executor, then applies Quality Gates and persists accepted results. `BaseExecutor`
owns strict generation/validation; `production_model_call` is a single-request
capability over `openai_text.chat`. PostgreSQL owns attempts and fencing.

`ModelResponseError.reason` accepts only `ModelResponseFailureReason`:

| Provider condition | Internal reason | Graph retry |
| --- | --- | --- |
| incomplete, max_output_tokens | incomplete_max_output_tokens | terminal |
| incomplete, content_filter | incomplete_content_filter | terminal |
| incomplete, unknown/missing/malformed reason metadata | incomplete_other | terminal |
| refusal block | refusal | terminal |
| invalid JSON/envelope, absent text, unexpected status | invalid_envelope | terminal |

No provider text is placed in the exception; decoder context is suppressed.
Refusal is checked before the convenience `output_text` shortcut. Completed
nonempty text and usage retain their successful return shape; JSON semantics
remain the executor's responsibility. The legacy refusal exception also uses
the safe enum, without changing legacy retry ownership.

The rejection warning contains only `reason`, configured `model`, effective
`max_output_tokens`, and optional `output_tokens`/`reasoning_tokens`. Counters
must be exact nonnegative integers within the effective budget; bools, strings,
floats and excessive values are omitted. Reasoning usage cannot exceed validated
output usage when available; otherwise it is bounded by the effective budget.
No response, prompt, schema, evidence or refusal text is logged.
Graph failures retain the existing safe `execution_invalid` persistence code.

## Bounded generation policy

`app/model_generation_policy.py` defines the runtime-neutral internal enum
`ModuleOutputBudget`. Every executor defaults to GENERIC (4000). Only Positioning
with the complete server Registry output set selects POSITIONING_FULL (16000).
Partial Positioning, other modules, intent interpretation and owned-site
extraction keep 4000. Names are validated before generation; user text never
selects a profile. Arbitrary numeric budgets are rejected by the adapter, and
numeric transport overrides alone still clamp to `MAX_OUTPUT_TOKENS_CAP=4000`.
The profile override requires strict JSON Schema single-attempt mode.

Capacity inspection distinguishes expected concise output from field maxima:

- There are 16 accepted requested statements. Each permits 4000 characters,
  32 local and 32 parent references of up to 128 characters. Assumptions and
  limitations each permit 12 strings of 4000 characters. The wire list allows
  32 statements, but exact output coverage rejects extras.
- Filling all fields for 16 statements produces 296296 compact ASCII JSON
  characters (using the actual output names and longest kind/confidence labels),
  already exceeding the existing executor limit of 131072 raw characters.
  Non-ASCII JSON escaping can increase serialized size further. These permissive
  maxima are not an expected response size or a guarantee of successful generation.
- A synthetic Russian concise-response sizing experiment used 16 statements,
  two 52-character SHA-based local references and two parent references per
  statement, and two 180-character assumptions plus two limitations. With
  250/500/1000 characters per statement, compact JSON measured
  10252/14252/22252 characters, 14336/21776/36656 UTF-8 bytes and
  3584/4384/5968 visible tokens using `tiktoken`'s `o200k_base` encoding.
  This is synthetic sizing, not a provider usage or quality measurement.

16000 provides roughly 10000 tokens of additional reasoning/formatting headroom
over the 1000-character example. It is a deterministic cost bound, not a proof
that every schema-valid response fits. Actual usage and latency need monitoring;
an exhausted response fails closed without a second request or graph retry.
The four request-scoped Positioning schemas, semantic/evidence gates and existing
131072-character validation bound are unchanged.

## Reasoning and compatibility

Repository default hard model is `gpt-5`; `.env.example` uses `gpt-5-mini`;
the local configured model inspected for this task is `gpt-6-sol`. The deployed
server configuration is unavailable. No model is switched. Structured calls
retain `reasoning.effort=low`, verified for these configured model IDs on the
offline transport boundary.

The [GPT-5 model documentation](https://developers.openai.com/api/docs/models/gpt-5)
lists minimal/low/medium/high; the
[reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
explains that max_output_tokens covers both reasoning and visible tokens.
Lower reasoning can reduce consumption, but changing synthesis effort without
production model identification and semantic quality evaluation would add a
separate behavior change. It is deferred; support is not inferred from an ID
prefix, and no new unsupported effort is sent.

This extends only the internal ModuleModelCall keyword capability. Injected
implementations must accept `output_budget` (the default is GENERIC). Neither
public ExecuteRequest nor persisted requests/plans/interpretation identities
gain fields. Registry remains 1.3.0; historical JSON and migrations are unchanged.

## Verification

Transport regressions cover completed responses, all failure reasons, malformed
2xx envelopes, HTTP 400 preservation, safe logs/tracebacks, malformed counters,
and exactly one provider request. Budget tests verify executor selection,
real HTTP payloads, arbitrary-budget rejection, generic cap preservation and
unchanged reasoning/model settings. Every bounded reason is terminal through
the worker, including wrapped causes. Existing four-schema and product-truth
regressions remain required. The PostgreSQL strategy regression executes the
production HTTP adapter with both strategic seeds absent, accepts 16 claims,
persists POSITIONING success and makes VIRTUAL_CMO pending.
