# POSITIONING: investigation and safe replay

Investigation date: 2026-10-12. Base: `origin/master`, commit `5a338f5`.
Scope: diagnostics and offline tests only. Production model, budgets, Expert Core,
schemas, Quality Gates and retries are unchanged. No deployment or real provider
requests were made during this investigation.

## Evidence and conclusion

The incident supplied by the operator concerns run
`24387ccc7a22b01fc6bcd8189686221826ff3b1002e04f54baabcb6194bf72c7`, job
`be9baf5c41a98c4d870c4850d0f9297a`: POSITIONING, `failed`,
`provider_transient`, attempts=3, `gpt-5-mini`, budget 16000. The reported envelope
is `incomplete/max_output_tokens`, with input/output/reasoning usage all zero and
`output=[]`. Correlation IDs:
`req_de67dcc84fcb412687913db66c21d028`,
`req_793170f9962f40a398c6742618c7f0a0`, and
`req_87d0826eee7a44ec8b4bbe487cc7171d`. All three requests are
operator-confirmed `incomplete_empty_max_output_tokens` failures with zero
input, output and reasoning tokens and empty output.

These are supplied observations, not independently retrieved production records.
Production DB access, historical deployment revision/configuration and provider
request traces were unavailable in this workspace. The actual incident input and
schema were consequently not reconstructed here. No business snapshot was saved.

**Established application mechanism:** the empty zero-token envelope is classified
as `INCOMPLETE_EMPTY_MAX_OUTPUT_TOKENS`. That reason alone is retryable among the
incomplete response reasons. The graph worker maps it to `provider_transient`;
after the third failed attempt, the service makes the job and run terminal. This
explains the status and repeated attempts, but does not establish why the provider
returned this envelope. In particular, zero reported reasoning/output tokens do
not prove that 16000 tokens were consumed. Reporting errors remain possible.

**Root cause of the provider anomaly remains unconfirmed.** Increasing production
budgets or changing models/Core would therefore be premature. The next evidence
is the safe replay fingerprint and controlled provider comparisons below.

## Authoritative execution path

1. `OrchestrationPlanRecord.compiled_plan_json` is decoded by `plan_from_json`.
   `GraphExecutionService._plan` requires active revision 1, matching source ID,
   Registry version and fingerprint, and validates the compiled graph/bindings.
2. `_graph_state` validates every job route and artifact envelope/fingerprint,
   successful producer job, recomputed Quality Gate acceptance and complete
   accepted claims. `_ready` enforces hard dependencies and terminal optional
   dependencies. `_upstream` restores the full ancestor closure, not just direct
   parents. `_coverage` adds explicit limitations to the context packet.
3. `load_work` creates `ModuleExecutionRequest` with job ID as execution identity,
   persisted objective, output names, context and accepted upstream results.
   Production `load_work` also checks/locks its active lease; diagnostic `restore`
   deliberately uses only the SELECT/evaluation helpers and constructs the same
   request without `_active`, `claim`, `_run`, JobExecution or run-status checks.
4. `ModuleGraphWorker` dispatches the persisted binding to `PositioningExecutor`.
   `prepare` checks module/output compatibility. Required first-party inputs are
   product, target/target hypothesis and product truth. Optional job/alternative
   seeds choose the precise output schema variant. Full 16-output POSITIONING
   selects the server-owned `POSITIONING_FULL` budget (16000).
5. `BaseExecutor.generate` builds first-party evidence with stable IDs derived
   from module/job/fact identity, extracts accepted within-scope parent claims,
   and calls `support_response_schema`. The request-specific schema adds support
   allowlists, removes unavailable support branches and limits empty families.
6. `ExpertInstructionComposer` composes one validated Core, specialized module,
   response mode and precedence rules. Already composed values are validated and
   returned unchanged; reserved markers in raw components are rejected.
7. `generate` serializes objective/output names, scoped context, local evidence,
   accepted upstream payloads and allowed parent IDs. Unauthorized facts never
   enter the generated scoped fact list. Evidence values also appear in context;
   upstream payloads carry both wire output and normalized claims. This is
   intentional provenance representation with repeated data, not duplicated Core.
8. `production_model_call` delegates to `app.llm.openai_text.chat` with
   `single_attempt=True`. The transport POSTs to configured
   `OPENAI_BASE_URL + /responses`. JobExecution owns subsequent attempts.

Plans persist execution contracts and business context, not rendered prompts,
Expert Core/model configuration or a historical HTTP body. Replay uses the code
and configuration selected by the operator. A byte-exact historical assertion
requires the deployed revision, Core checksum, incident model, dependency versions
and unchanged accepted artifacts. Current terminal graph coverage may differ
from an earlier attempt in a concurrently progressing run; compare fingerprints
and incident component sizes before interpreting probes.

## Exact production wire contract

| Field | Actual builder behavior |
| --- | --- |
| `model` | `settings.DEFAULT_TEXT_MODEL_HARD`; code default is `gpt-5`, reported deployment used `gpt-5-mini` |
| `input` | Two plain string-content messages, roles `system`, then `user` |
| `instructions` top-level | Absent; composed instructions are in the system message |
| `reasoning` | `effort=low`; structured output transport sets this explicitly |
| `max_output_tokens` | 16000 for all POSITIONING outputs; 4000 for a subset |
| `text.format` | `type=json_schema`, `name=module_output`, `strict=true`, exact request-owned schema |
| Additional fields | No temperature, tools, stream, previous response ID or explicit store setting |
| Retries/fallback | One HTTP call; no schema fallback, repair or budget expansion |

Offline tests compare the diagnostic payload with the real production adapter and
HTTPX MockTransport body, and compare reconstruction with production `load_work`.
They pin the instruction size/hash and explicit wire fields, and cover accepted
and failed optional upstreams. They also exercise the reported zero-token envelope.

OpenAI documents that output budgets include visible and reasoning tokens, and
that incomplete responses may occur at the token limit. That does not explain
the supplied zero-usage anomaly by itself:
[Responses reference](https://developers.openai.com/api/reference/resources/responses/methods/create),
[reasoning guide](https://developers.openai.com/api/docs/guides/reasoning).
Unsupported strict schemas normally produce an error, rather than proving this
specific incomplete envelope:
[Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Expert Core inspection

Measurements from the canonical normalized resource and actual POSITIONING builder:

| Component | UTF-8 bytes |
| --- | ---: |
| Expert Core 1.0.0 | 49876 |
| Specialized POSITIONING instructions | 1280 |
| Response mode | 1306 |
| Precedence, markers, separators | 689 |
| Complete instructions | 53151 |

Complete instruction SHA-256:
`33a422ace7494db1953b3736a8ba83b9399b2b6a8eb7126801dc7d3f1ac865a3`.
Core normalized SHA-256:
`5dad2b61b14c6a137668bd7ed0a5ee3b5cff45235d7c79726337b1e3529d72f9`.
The measured 53151 instruction bytes exactly match the supplied incident size.
The Core is about 93.84% of those bytes and appears exactly once. Bytes must not
be interpreted as token counts, especially for this Russian/English resource.
Incident input=22827 and schema=8048 are operator observations; synthetic fixture
sizes differ and do not establish incident fact/support counts.

There are 59 numbered sections plus the introductory role section. Semantic
reinforcement is present: evidence/classification/confidence/no invention (§6,
8–11, 22, 34, 50, 56–57), framework restraint (§4, 7, 27, 51), business economics
(§12–18), and closing principles (§58–59). Causality is covered in §16–17 and
repeated in §56. Recommendations/alternatives/risk/testability (§37–40),
measurement, Russia/currentness, channels, customer journey and operational
capacity cover a much broader scope than a bounded POSITIONING output.

Potential instruction tension: §37 expects a broad recommendation analysis,
§44 decision logic and §57 a 23-question final check, while response mode requires
concise bounded JSON statements. These can increase reasoning work. However,
§37 does not require displaying every label, §45 permits task-specific adaptation,
§55 discourages excessive analysis, and both Core and response mode forbid
revealing hidden reasoning. No confirmed syntactic format contradiction or
double composition was found. Removing repetition is a separate design/evaluation
change, not an established remedy for this incident.

## Read-only tool

Run from the chosen deployment-compatible checkout, as a standalone process:

```sh
python -m tools.positioning_diagnostics --snapshot /secure/incident.diagnostic-snapshot.json --run-id RUN_ID --job-id JOB_ID
python -m tools.positioning_diagnostics --database-read --run-id RUN_ID --job-id JOB_ID
```

Default snapshot mode needs no usable DB credentials or API key and opens no DB
connection or real HTTP client. The real executor and wire builder are intercepted
in memory before any POST. No provider response or Quality Gate result is created.
The optional DB reader uses configured PostgreSQL with a transaction whose first
statement is `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`, validates
the workflow identity and uses only production SELECT/evaluation helpers. There
are no lease claims, `FOR UPDATE`, state transitions, queue wakeups or writes.

Default stdout is only component byte counts/SHA-256 hashes, fact/support/output
counts, Core version/copy/section counts and per-section numbered size/hash pairs,
plus matrix payload size/hash pairs. Schema hash serialization is UTF-8 JSON with
sorted keys and compact separators; input/instruction hashes preserve their exact
strings. Production rejection logs serialize schema compactly without sorted keys;
key ordering changes hashes, not schema byte counts. Whole-payload hashes are
canonical JSON hashes, not hashes of HTTP headers or exact network framing.
All third-party logging is disabled by the standalone CLI; errors are closed
labels with no tracebacks, raw values, URLs or credentials. Do not embed this
process-global interception in an application worker.

Snapshot contract: JSON object with `schema_version=positioning_diagnostic_snapshot.v1`:

- `run`: `run_id`, `workflow_type`, `status` (terminal `failed` is supported).
- `plan_record`: `run_id`, `revision`, `status`, `source_plan_id`, `registry_version`,
  `compiled_plan_fingerprint`, `compiled_plan_json`.
- `jobs`: run-scoped rows with `job_id`, `marketing_run_id`, `kind`, `workflow_step`,
  `status`, `error`, `payload_json`, `result_json`.
- `artifacts`: run-scoped rows with `run_id`, `artifact_key`, `artifact_type`, `step`,
  `payload_json`.

Obtain these projections in one consistent read-only snapshot using approved
operator access. JobExecution is neither needed nor exported. Keep snapshots in a
protected local directory outside Git; use the `.diagnostic-snapshot.json` suffix,
which this PR ignores defensively. The tool does not export raw snapshots or prompts.
Snapshot files are bounded to 16 MiB. Invalid routing, plan/artifact identity,
duplicate rows, producer success or acceptance mismatches fail closed.

## Controlled matrix and interpretation

| Case | Change from baseline | Question / limitation |
| --- | --- | --- |
| `baseline` | None | Does the reconstructed request reproduce the provider anomaly now? |
| `no_core` | Remove only canonical Core text; retain precedence/module/response mode | Is Core size/content implicated? Does not separate size from semantics. |
| `small_context` | Replace user input with synthetic objective/output/support IDs | Is business context implicated? Removes semantic support; completion is diagnostic, never an accepted business result. |
| `simple_schema` | Same JSON root/statement shape; remove output branches/support enums/bounds | Is schema complexity implicated? Looser schema cannot demonstrate production semantic correctness. |
| `alternate_model` | Change only model, with explicit operator-selected model ID | Is failure model-specific? Model must support low reasoning and strict output; incompatibility is inconclusive. |

Other fields, output budget and single-POST behavior remain fixed. All variants are
diagnostic values in memory; nothing is persisted into the graph. Even offline,
the original replay payload is immutable with respect to variant construction.
To execute a bounded batch only after explicit authorization:

```sh
python -m tools.positioning_diagnostics --snapshot /secure/incident.diagnostic-snapshot.json --run-id RUN_ID --job-id JOB_ID --live --max-calls 2 --case baseline --case no_core
```

`--live`, explicit `--case` selections and `--max-calls` are all required. Maximum
is 4 calls per invocation, no automatic retries, no duplicate cases. A model case
also requires `--alternate-model`. Policy is checked before loading snapshots/DB
or constructing clients. The callable probe also requires explicit `opt_in=True`.
Response texts, schemas, prompts and keys are never printed; only closed envelope
labels, bounded usage/item counts, HTTP status and validated request IDs are returned.
No cases were run against a real provider in this investigation.

Use baseline and each ablation as pairs in separately authorized batches. One
successful ablation is suggestive, not causal proof: repeat paired comparisons
under a separately approved budget to distinguish intermittent provider behavior.
The four-call cap is per process invocation, not a global billing quota.

Hypotheses and discriminating evidence:

1. Provider or intermediate gateway anomaly: correlate the incident request IDs
   with provider-side status/account/model traces. Compare baseline reproduction
   and supplied usage values; verify deployed base URL through secure operator
   access, without printing it. Identical failure across ablations strengthens
   this explanation; intermittent results need paired repeats.
2. Instruction/context/schema workload interacting with `gpt-5-mini`: an unchanged
   baseline failure plus repeated successful one-factor ablations or model swap
   supports this hypothesis. Compare only envelope completion, not business quality.
3. Genuine reasoning exhaustion or incorrect usage reporting: normally exhausted
   output/reasoning usage would support the first; this incident reports neither.
   Request provider accounting traces before treating the reason label as proof.
4. Deployed payload differs from repository contract: first compare replay
   instruction hash/size, schema/input sizes, deployed commit/config and accepted
   upstream identities. Resolve any mismatch before interpreting live probes.

No production fix is included. If provider traces establish an anomaly, address
that confirmed provider/gateway condition separately. If controlled evidence
establishes workload-related exhaustion, propose the smallest isolated change to
the implicated component, with POSITIONING semantic/quality evaluation and explicit
approval for any live validation. This PR does not preselect a model, budget,
Core, schema, Quality Gate or retry change.

## Validation

Offline suite: diagnostic replay/privacy/guards plus POSITIONING output/seeds,
graph adapter, Expert Core/integration, production worker and strategy builder.
The original focused suite passed 331 tests, but full CI subsequently exposed two
architecture-boundary failures (2847 passed, 2 failed). The standalone CLI is now
in `tools/positioning_diagnostics.py`; no architecture-test exceptions or production
dependency changes were added. The updated tests also run the public module CLI
in a subprocess with real HTTP clients and DB sessions blocked and check output privacy.
Final exact-HEAD CI and container-smoke results are recorded in PR #111.
`git diff --check` is required before publishing the update.
PostgreSQL enforcement is specified by the read-only transaction
and its call-order test; a real production DB integration was not run here.
Final diff review must verify only diagnostic/test/documentation/ignore additions
and unchanged production files.
