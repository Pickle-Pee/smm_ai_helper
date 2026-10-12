# EXPERIMENTS output budget and context audit

## Incident and bounded fix

Run `1a35285a4c0a675b4eeda57f20a4a948586718a22ff734a078b9a130f4e362cc`
completed POSITIONING and VIRTUAL_CMO, then failed EXPERIMENTS with
`execution_invalid`, attempts=1, `incomplete_max_output_tokens` on gpt-5-mini.
Reported usage: 45265 input tokens, 4000/4000 output tokens, 128 reasoning
tokens; input text 116388 bytes, instructions 53096 bytes, schema 7034 bytes.
The existing executor inherited GENERIC=4000 despite requesting all 16 outputs.

The execution path is production graph worker -> dispatcher -> ExperimentsExecutor
-> BaseExecutor.generate -> production_model_call -> chat(single_attempt=True)
-> POST /responses. PostgreSQL owns durable attempts and terminal job state;
the worker classifies real max-output exhaustion as execution_invalid, with no
retry. Registry 1.3.0 owns the production output set; earlier execution registry
versions retain the same EXPERIMENTS output names. No runtime implementation is
duplicated by this change.

EXPERIMENTS_FULL is a distinct server-owned enum profile with a 16000-token limit.
It is selected by exact set equality with the Registry's complete EXPERIMENTS
outputs, including reordered requests. All proper subsets retain GENERIC=4000.
User objective/context text cannot select the profile. The audit found no partial
production incident establishing a need for another profile; large partial
responses can still exceed GENERIC. Partial coverage is not a capacity guarantee.

No model, reasoning effort, schema, Quality Gates, numeric/provenance checks,
context construction, business contract, persisted fields or other module budgets
change. No migration is necessary. Transport still makes exactly one HTTP request
per durable attempt. Genuine exhaustion remains terminal; no expansion, fallback,
repair or additional LLM calls are introduced. Existing confirmed empty-response
anomaly handling from PR #109 is unchanged.

## Offline capacity assessment

Reproduce with `python tools/measure_experiments_budget.py` in the repository
environment with optional `tiktoken` installed (not a new runtime dependency).
Uses o200k_base and the current Unicode JSON serialization with spaces. No provider
generation is involved. The Russian fixture covers each of the 16 results and
three distinct ExperimentDesign objects, including minimum inputs and strategic
references. The compact fixture passes the production adapter, scoped schema,
executor validation and real Quality Gates. Expanded repeated-prose scenarios
are structural stress probes, not semantic-quality evaluations.

| Prose factor | Parents per result | Max result chars | Visible tokens | Plus incident's 128 reasoning tokens | Headroom at 16000 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Compact x1 | 1 | 323 | 3693 | 3821 | 12179 |
| Compact x1 | 8 | 323 | 7117 | 7245 | 8755 |
| Expanded x3 | 8 | 971 | 9231 | 9359 | 6641 |
| Expanded x3 | 24 | 971 | 17503 | 17631 | -1631 |
| Stress x10 | 24 | 3239 | 24902 | 25030 | -9030 |

Every measured output has 16 results and three designs and passes the unchanged
request-scoped JSON Schema and Pydantic shape validation. Eight long opaque
references per result explain why even compact prose can exceed 4000. The 16000
profile gives useful headroom for the measured compact/moderate eight-parent
shapes; it does **not** cover every allowed shape. Twenty-four parents with
moderate prose already exceed it. Stress responses remain below the executor's
131072-character parser bound (76191 characters), so that bound is not a substitute
for token budgeting. Reasoning usage can exceed the incident's 128; the table is
an illustrative reserve, not a prediction. Live sufficiency cannot be established
without a fresh production run, which is outside this no-additional-LLM-call task.

## Input duplication audit (no context changes)

BaseExecutor.generate currently serializes authorized scoped facts twice:
`context.known_facts[*].value` and `local_evidence[*].value`. The fact object also
carries source, confidence, authorization and scope metadata, while local evidence
carries provenance IDs/input keys. Removing the entire fact object would discard
information, so the conservative estimate removes only equal duplicated values.
`relevant_project_context` is emptied before serialization and is not a third copy.

Accepted upstream results contain both structured `payload.outputs` and
`normalized_result.claims`. POSITIONING text repeats claim.value; VIRTUAL_CMO text,
items and numeric context repeat the structured StrategyClaim value, with additional
attribution in normalized numeric context. Support IDs, assumptions, limitations,
evidence and other metadata also repeat across representations. They carry identity
and acceptance semantics; an entire payload removal is only an upper-bound estimate.
`allowed_parent_claim_ids` is a separate allowlist, not interchangeable with the
upstream values. Failed/blocked upstream results are already excluded.

The reproducible synthetic input uses full POSITIONING (15 outputs), full CMO
(9 outputs), and an 8000-character authorized site/brand excerpt. Production
serialization is captured from the unchanged BaseExecutor, not reimplemented.

| Input measurement | o200k_base tokens |
| --- | ---: |
| Entire user input JSON | 26906 |
| context.known_facts | 1703 |
| local_evidence | 1730 |
| upstream_results | 22526 |
| allowed_parent_claim_ids | 795 |
| Instructions, measured separately | 7854 |
| Schema, measured separately | 2468 |
| Remove equal fact values only: potential savings | 1629 (6.1% of user input) |
| Also remove exact duplicated upstream text/items: potential savings | 2055 (7.6%) |
| Remove equal fact values and entire upstream payloads: upper bound | 10869 (40.4%) |

Components are counted independently and do not add exactly because tokenization
depends on surrounding punctuation. Savings are measured by retokenizing the
complete counterfactual JSON, not by adding component counts. These estimates
exclude instruction/schema savings, provider framing and any change to output.
The full incident request was not available, so these are **not** estimates of
tokens saved in that exact run; its reported 45265 input tokens cannot be safely
scaled by these percentages. A future context change must preserve every scoped
fact, source attribution, structured design, numeric-grounding boundary, accepted
parent identity and material support relationship. This PR leaves all of it intact.

## Verification

Regression coverage checks full/reordered sets, every single omission and prefixes
of every smaller size, exact schema equality through transport, unchanged configured
gpt-5-mini/low effort, realistic complete response acceptance, schema/provenance/
numeric rejection, and consumed-budget errors with one closed HTTP transport.
The PostgreSQL production strategy graph additionally checks EXPERIMENTS exhaustion
after successful POSITIONING/CMO: execution_invalid, attempts=1, no artifact,
no re-execution after advance or worker polling. The existing numeric-grounding
graph fixture now expects 16000 for its full EXPERIMENTS request.

Focused local suite: 228 passed. Full CI and container-smoke results are reported
on the PR for its exact HEAD revision.
