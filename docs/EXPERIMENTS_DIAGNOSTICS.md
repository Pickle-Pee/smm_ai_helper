# EXPERIMENTS: read-only production incident diagnostics

The CLI reconstructs an EXPERIMENTS module request from the persisted active plan,
Job routing, accepted artifact fingerprints, Quality Gate manifests and full
ancestor closure. It calls the real executor and production model adapter, but
intercepts the HTTP client before any connection. It does not claim a Job lease,
change JobExecution, enqueue work, write artifacts, or finish a graph.

## Run on the VPS

Check out this PR revision in a separate checkout and install `requirements.txt`.
Run as a standalone process, never import the CLI inside a running worker: the
capture temporarily patches settings and the HTTP factory in this process.
Use the same application configuration as production, preferably with a SELECT-only
PostgreSQL account. Do not print environment variables or copy secrets into reports.

```bash
python -m tools.experiments_diagnostics --database-read \
  --run-id 918f5a2504835cf4df57bc280579474cb5c68f77a40464c9e75f15021e5a7ac2 \
  --job-id de3a4436ce8189937533c8456c4ee8ab \
  > experiments-report.json
```

The database transaction sets `REPEATABLE READ READ ONLY` before its first SELECT.
This flag permits database reads only; it does not opt into provider calls.
Offline snapshot mode requires no database access:

```bash
python -m tools.experiments_diagnostics --snapshot incident.diagnostic-snapshot.json \
  --run-id 918f5a2504835cf4df57bc280579474cb5c68f77a40464c9e75f15021e5a7ac2 \
  --job-id de3a4436ce8189937533c8456c4ee8ab > experiments-report.json
```

Snapshot shape follows the existing POSITIONING table projection with
`schema_version: experiments_diagnostic_snapshot.v1`: `run` (run_id/workflow_type),
`plan_record` (run_id/status/revision/source_plan_id/registry_version/
compiled_plan_fingerprint/compiled_plan_json), `jobs` (marketing_run_id/job_id/kind/
workflow_step/payload_json/result_json/error/status), `artifacts`
(run_id/artifact_key/artifact_type/step/payload_json). Include all Jobs and artifacts
for the run, not just EXPERIMENTS. Preserve stored JSON and fingerprints exactly.
Snapshots contain private business data; keep them outside version control (the
`.diagnostic-snapshot.json` suffix is already ignored). The CLI bounds reads to 16 MiB.
It intentionally offers no raw wire export. Errors use closed codes without exception
text; reports contain counts, byte lengths, digests and fixed diagnostic labels.

Incident correlation (provider_transient / incomplete_empty_max_output_tokens):
`req_981355c967804b69a1b84e0763567641`,
`req_bbec1207eb63462a88e32c8dfa90a77c`,
`req_825eb9f911744891814d31e6a4c93dc7`.
Reported envelopes had output=[] and zero usage; model gpt-5-mini, budget 16000.

## Interpretation and technical conclusion

The authoritative path is GraphExecutionService `_plan`/`_graph_state`/`_ready`/
`_upstream`/`_coverage` -> ModuleExecutionRequest -> ExperimentsExecutor.execute ->
BaseExecutor.generate -> support_response_schema -> production_model_call -> chat.
The diagnostic parameterizes the existing POSITIONING restore helpers by module;
it does not implement another graph reader. Full ancestor closure and re-evaluated
Quality Gates prevent arbitrary or partially accepted claims becoming parents.

EXPERIMENTS is an optional graph node. Its later failure must not be injected into
its original pre-dispatch coverage. The shared diagnostic excludes the target from
coverage calculation while retaining upstream failure limitations. Current builders
and current accepted artifacts cannot certify a historical byte-for-byte replay if
code/configuration or upstream state changed since dispatch. The report states this
limitation and compares exact UTF-8 input/instruction sizes with 102054/53096, and
canonical compact schema size with 7199. Schema key sorting changes order/digest but
not byte length relative to the production rejection logger. It also reports current
model/budget, component digests, deltas and serialization conventions. A size match
alone does not establish content identity; original incident digests were not supplied.

Two independent hypotheses remain:

- **Schema structure:** EXPERIMENTS uses `SupportRequirement.ANY`, without a provider
  projection override. With local evidence and parent claims its statement support
  OR has two branches. The proven single-branch collapse is a no-op for that shape;
  it is measured but excluded from live arms. With parent-only support it can apply,
  provided the actual request schema passes the production proof. No union flattening
  or support relaxation is performed.
- **Context size:** context facts and local evidence can repeat exact values;
  upstream payload fields can repeat normalized claims, including JSON-encoded CMO
  summaries. Counts/byte estimates describe structural repetition only. Equal leaves
  include labels/identities, pair totals can overlap, and they are not token savings
  or authorization to delete context. The input remains identical in every schema arm.

`ExperimentDesign` has eight required fields: five strings of 1–300 characters,
minimum inputs (1–5), constraints (0–8), strategic references (1–8 strings, 1–128
characters). The provider schema does not enum-bind or require unique strategic
references. The executor requires unique references drawn from accepted within-scope
POSITIONING/VIRTUAL_CMO HYPOTHESIS claims, and each canonical output must reference
at least one such parent. Its eligibility helper does not separately inspect a
materiality field; the graph enforces artifact/claim acceptance. General statement
support enums allow other accepted parents too. Runtime also narrows statement kind
to HYPOTHESIS/RECOMMENDATION, preserves constraints verbatim and rejects invented
numbers. CMO numeric_context quotes cannot serve as numeric assertion support.
These semantic checks are unchanged and are not fully expressed by provider schema.

Offline synthetic audits (one local evidence + one strategic parent) measured 4960
compact schema bytes, four definitions, eight references, one two-branch OR and no
single-branch OR. Parent-only measured 3936 bytes, collapsing equivalently to 2970.
A full synthetic strategy graph with accepted POSITIONING and VIRTUAL_CMO artifacts
produced 53096 instruction bytes (matching the incident), 49126 input bytes and
6539 compact schema bytes, with 25 strategic parents and one two-branch support OR.
These measurements are fixture evidence, not the incident's actual schema. The
incident snapshot/database is needed to obtain the actual cardinalities and report.
No production database or live OpenAI call was used during implementation. Three
empty incomplete envelopes with zero usage do not prove schema or context causality.

## Separately authorizable A/B probes

After reviewing the actual offline report, propose at most these pairs; approve
one pair at a time (two provider calls), preserve input/instructions/model/budget,
and do not interpret a single stochastic result as proof:

1. baseline vs `no_annotations`: remove schema annotations only.
2. baseline vs `inline_refs`: bounded local acyclic ref expansion, only if proof
   succeeds; expanded schema may be larger and provider compatibility is unverified.
3. baseline vs `collapse_single_support_anyof`: only if proof succeeds **and** the
   actual schema changes. A two-branch-only EXPERIMENTS schema makes this unavailable.

The CLI supports future explicitly authorized probes with `--live --case baseline
--case no_annotations --max-calls 2`. Do not use these flags for offline investigation.
The hard limit is four calls, one POST per selected distinct available arm, no retry.
Missing opt-in/limit, duplicate arms, proof refusals and no-op arms fail before client
construction. Responses are summarized without output text. Context-reduction probes
need a separate semantic design and authorization; they are not implemented here.
No probe results are accepted into production state.
