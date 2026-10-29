# POSITIONING provider schema experiment (#137)

Base: `4685ce680df524617b2050cc293c592d29d67ed8` (current master after
PR #136, merged 2026-10-29 22:35:02 UTC; python and container-smoke SUCCESS).
PR #135 supplies transport hardening; #136 supplies request telemetry and bounded
workflow governance. Neither is replaced. Support case #17194705 remains unresolved.
No production access/deployment, model/provider switch, token expansion or paid
provider request is part of this change. **The schema-causality hypothesis is unproven.**

## Execution trace and ownership

1. `app/module_registry/v1.*.json` descriptors and `registry.py` bind POSITIONING
   to `positioning.v1` for executable registries 1.1.0–1.3.0. Registry 1.0.0 is metadata only.
2. `orchestration_runtime/composition.py` constructs the explicit executor registry
   using Settings. `module_execution/dispatcher.py` checks the exact binding and
   dispatches a `ModuleExecutionRequest`; `orchestration_runtime/service.py` owns
   durable graph jobs, accepted predecessors and subsequent gate/persistence decisions.
3. `PositioningExecutor.prepare/execute` checks requested outputs and blocking
   product, target and product-truth facts. Scoped facts become local evidence.
   `output_type_for` selects one of four Pydantic schemas according to optional
   customer-job and alternative seeds. The output version remains `positioning.payload.v1`.
4. `BaseExecutor.generate` derives accepted parent claims, builds the authoritative
   request-scoped `support_response_schema`, including exact evidence/parent ID
   allowlists and support floors, and creates its independent JSON Schema validator.
   The optional product-support wire layer remains a separate existing experiment.
5. Only `PositioningExecutor.provider_schema_for` changes under the new flag. The
   original validator remains intact. Expert Core, specialized instructions, expected
   outputs, scoped context, local evidence and accepted predecessors stay identical.
6. `orchestration_runtime/model_adapter.production_model_call` uses configured
   `DEFAULT_TEXT_MODEL_HARD`, the existing server-owned output-budget enum and
   `single_attempt=True`. `llm/openai_text.chat` produces POST `/responses` with
   `input`, `model`, `max_output_tokens`, `reasoning.effort=low` and
   `text.format={type:json_schema,name:module_output,strict:true,schema:...}`.
   Full POSITIONING uses 16000 tokens; subsets use 4000. No budgets are changed.
7. Envelope validation rejects incomplete/refusal/malformed responses before output
   parsing. For completed text, duplicate/nonfinite JSON checks and the 131072-character
   bound precede original JSON Schema and strict Pydantic validation. Coverage,
   duplicate citations, local/parent identity, missing support, product truth, seed
   semantics and confidence clamps still apply. `evaluate_result` runs Quality Gates
   before accepted artifacts can be persisted. No schema fallback or local retries.

PostgreSQL remains the owner of jobs, attempts and artifacts; Redis carries wakeups.
This experiment owns only an injected process configuration and fresh provider
schema dictionaries. No persisted/public schema, lifecycle or migration changes.

## Schema analysis and compatibility

The current schema repeats complete statement objects inside support `anyOf`,
and separates statement variants by output name/kind. Identity allowlists depend
on request evidence and accepted parents. Four seed states produce different schemas.
The checked-in [hash report](positioning-schema-experiment-hashes.json) measures
deterministic synthetic inputs, five/three/four evidence IDs and no accepted parents;
it does **not** claim to fingerprint the original incident payload. The offline
snapshot mode measures the exact restored request when a local snapshot is available.

| Seeds (job, alternative) | Original bytes | Property / required occurrences | Enum values | Definitions | Container depth | Minimal bytes |
|---|---:|---:|---:|---:|---:|---:|
| yes, yes | 4448 | 27 / 27 | 61 | 3 | 4 | 644 |
| no, yes | 7545 | 51 / 51 | 84 | 5 | 4 | 644 |
| yes, no | 7553 | 51 / 51 | 84 | 5 | 4 | 644 |
| no, no | 7434 | 51 / 51 | 75 | 5 | 4 | 644 |

Counts include repeated schema declarations, not just distinct output keys.
Depth resolves local references and counts object/array containers, with root=1;
composition applies at the same instance depth. Minimal depth remains 4, with two
objects, 9 property/required occurrences, zero definitions, refs, enum/const or
composition nodes. The report also includes keyword counts, resolved anyOf depth,
string-character totals, allowlist sizes and documented-limit checks. Accepted
parent support introduces another allowlist and retains both support alternatives;
offline compatibility tests cover both parent topologies and all seed states.

The minimal schema contains only `type`, `properties`, `items`, `required` and
`additionalProperties:false`. Root assumptions/limitations remain string arrays;
outputs remains an array of closed statements with output_name/text/kind/confidence
strings and evidence_ids/parent_claim_ids string arrays. It removes provider-side
annotations, bounds, enums, refs, output union and support OR, without renaming,
dropping or translating response fields. Every valid local payload fits this
envelope; the converse deliberately does not hold. Invalid envelope-conforming
responses still fail the original local contract. No repair or fabricated support.

The official [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)
requires closed objects and all fields required and supports only a JSON Schema
subset. These shape requirements are retained. The measured original examples do
not exceed documented schema limits; **JSON Schema validity/offline shape checks
do not establish actual provider acceptance or explain the incomplete response**.

POSITIONING currently has no separate numeric_context contract; this PR does not
introduce one or claim a new numerical safety guarantee. Existing numerical support
and grounding in MARKET_ANALYSIS, VIRTUAL_CMO and EXPERIMENTS, downstream provenance,
and all Quality Gates remain authoritative and unchanged. Tests compare all five
other executors' complete model arguments and results with the flag on/off; the
existing numerical regression suites run in full Python CI.

## Opt-in and rollback

`POSITIONING_MINIMAL_PROVIDER_SCHEMA_ENABLED=false` by default. Enable only in a
separately approved isolated experiment. Composition injects it only into POSITIONING.
Both `POSITIONING_SCHEMA_PROJECTION_ENABLED` and
`POSITIONING_PRODUCT_SUPPORT_WIRE_ENABLED` must be false: conflicting configurations
fail at executor construction before provider calls. The equivalent projection
experiment remains unchanged and is not silently chained with this broader envelope.

Rollback: set the new flag to false and reconstruct/restart the runtime in the
approved environment. Original provider payload construction is restored exactly.
No data migration, artifact rewriting, production change or merge is needed.

## Offline reproduction and hashes

With disposable/test settings and installed requirements:

```powershell
$env:DATABASE_URL='postgresql+asyncpg://test:test@localhost:5432/offline'
$env:TELEGRAM_BOT_TOKEN='offline'
$env:OPENAI_API_KEY='offline'
python -m tools.positioning_schema_experiment
python -m tools.positioning_schema_experiment --snapshot local.diagnostic-snapshot.json --run-id RUN_ID --job-id JOB_ID
```

The tool has no live option or database mode. It replaces the HTTP client before
construction and intercepts POST before any network request. Original and minimal
payloads pass through the production executor and adapter; an assertion proves
that `text.format.schema` is the only changed path. It emits counts/hashes only,
never prompts, facts, support identities, response text, authorization or endpoint.
Snapshot restore uses existing plan/dependency validators without database access.
Run standalone, because capture temporarily patches HTTPX and Settings.

The committed synthetic capture uses the current configured default `gpt-5`, low
reasoning, 16000 tokens. Package versions are included. Canonical SHA-256 uses UTF-8,
sorted keys, compact separators and ensure_ascii=False. A separate `http_body`
SHA-256 uses the exact HTTPX JSON-body serializer with insertion order (no headers).
Hashes change with inputs, identities, instructions or serializer/schema versions.

For the both-seeds fixture, exact HTTP-body SHA-256:

- Original: `e955afde711fe6011dfaf20da2a2d62ff901d4f142bd5d03b6e55c5952420db6`
- Minimal: `93d237e9421915130a1b96550aced65c2b62723cb3eac7f91c938e119aeb4425`
- Shared payload without schema (canonical): `57cb842a5d6616fd792d448969d9939a6002756c66dd5cc70ad506e9465e5cce`

See JSON report for every seed state's full payload and schema SHA-256, byte sizes
and structural differences. These are prepared payloads, not evidence of sent calls.

## Separately authorized live diagnostic protocol

No live run has been authorized or performed. After explicit permission for a fixed
cost/call bound, freeze one restored request and record its two offline hashes.
Use an isolated runner with no DB writes and disabled workflow retries, same endpoint,
credentials/project, exact configured model, instructions/input, reasoning effort,
token budget, timeout and strict format. Send exactly one original and one minimal
request; prohibit automatic retries, budget expansion, repair and schema fallback.
Record planned order; one pair is exploratory and is not statistically conclusive.
Any additional randomized/reversed pairs require separate bounded approval.

Collect per call: HTTP status, provider request/response IDs, elapsed time,
response status and incomplete reason, output item/text counts, usage and its
known/unknown state, transport outcome and original local acceptance/gate result.
Treat missing usage or timeout as unknown outcome, not zero cost. Retain sensitive
data only in the approved local environment; share bounded metadata/hashes.

Success evidence: original reproduces empty incomplete/max_output_tokens while
minimal completes, passes the original JSON Schema/Pydantic/semantic checks and
Quality Gates, at identical controls. Require reproducibility in separately approved
pairs before causal attribution or any rollout. Both succeed: incident not reproduced.
Both fail: hypothesis unsupported. Minimal completes but local validation/gates
reject: experiment fails. Any extra factor changes: comparison invalid. An unchanged
offline hash or smaller schema alone cannot confirm the hypothesis or close #17194705.

## Verification matrix

| Case | Expected evidence |
|---|---|
| Four seed states, parents present/absent | Same accepted local result and Quality Gates in both modes |
| Invalid IDs, missing support, seed kind, unknown names/confidence, length/type/extra fields | Same fail-closed local rejection |
| Coverage, duplicate IDs, wrong product evidence, Pydantic whitespace | Same stage; one model call; non-retryable output error |
| Provider mutates schema | Original validator remains independent |
| HTTP 200 empty incomplete/zero usage | Existing transport classification; one POST; same 16000-token budget |
| Production composition flag off/on | Exact expected HTTP payload, only schema changes |
| Other five modules and numeric support | Identical model arguments/results; existing numerical regressions |
| Offline report | Deterministic hashes, production payload builder, no real client constructed |
| Conflicting flags | Fail before provider call |

Required checks: new focused tests, neighboring POSITIONING/transport/numerical
regressions, full repository Python CI and container-smoke on the final PR revision.
No database migration is added. Real provider acceptance and causality remain unverified.
