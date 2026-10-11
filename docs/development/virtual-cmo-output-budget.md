# VIRTUAL_CMO generation budget

Base: `7f5b7cc479eef376fb13b964ee38302fe4c89798`, including PR #107.
Incident reference: `12c119476bad25f1220880e63374ca6c573067d8d51dd425a6adf5c0e79b497b`.

## Diagnosis and limits of the evidence

Reported POSITIONING succeeded in one attempt. VIRTUAL_CMO failed in one attempt
with `execution_invalid`; provider metadata says `gpt-5-mini`,
`incomplete_max_output_tokens`, budget 4000, output/reasoning usage both zero.
EXPERIMENTS did not start. No historical provider body was available for this investigation.

The authoritative path is the production graph runtime -> dispatcher ->
`VirtualCMOExecutor.generate` -> `production_model_call` -> `chat(single_attempt=True)`.
CMO previously inherited `BaseExecutor.output_budget_for`'s generic 4000 profile.
The model adapter supplies the exact request-scoped strict schema; the transport
rejects incomplete envelopes before accepting any text. The worker records a
terminal invalid execution, PostgreSQL owns job/attempt state, and Quality Gates
control downstream acceptance. The legacy non-single-attempt transport policy is
outside this change.

The previous rejection logger already distinguished missing usage from zero:
it added numeric fields only for actual nonnegative integer values. Thus these
reported zeros cannot be explained by a local missing-to-zero coercion in that
logger. If they came from that log, they are actual provider-reported zeros.
Another reporting layer's provenance cannot be verified from this incident summary.

[OpenAI reasoning guidance](https://developers.openai.com/api/docs/guides/reasoning)
defines the output limit as including reasoning and visible output. Token-cap or
context-window exhaustion can produce incomplete responses before visible text.
Zero total output **and** zero reasoning is not affirmative evidence of ordinary
reasoning-budget exhaustion. Provider/gateway incompatibility or incorrect usage
reporting remains a hypothesis, not a demonstrated root cause. An HTTP schema
rejection follows a separate path that preserves the HTTP failure without dropping
the schema or retrying.

## Bounded server profile

VIRTUAL_CMO now selects a dedicated 16000-token profile. Full POSITIONING stays
16000, partial POSITIONING stays 4000, and EXPERIMENTS and other generic callers
stay 4000. Profile identities are distinct even when token counts match (avoiding
Python Enum aliases). `module_output_tokens` remains the only conversion to an
integer. Profiles are internal, neither public nor persisted, so no migration is
needed. User objectives/context cannot select or override them.

PR #107 requires `numeric_context` on generated statements: up to three exact
source quotes of at most 1000 characters per output, each with an exact cited
support ID. Across nine outputs this adds up to 27 quotes/IDs, beyond rationale,
up to 25 qualitative items, evidence IDs, parent IDs, assumptions and limitations.
The schema itself is input, not generated output; its size alone does not prove
output-budget exhaustion.

Offline `o200k_base` sizing via `tools/measure_virtual_cmo_budget.py` uses nine
statements, eight 52-character parent IDs each, three numeric quotes each,
one/three items, and two assumptions/limitations each. It validates the structural
schema, not numerical entailment or provider schema compatibility. Tokenization
requires optional `tiktoken`; it is not a production/test dependency.

| Summary characters | Quote characters | Before numeric_context | With numeric_context |
| --- | --- | --- | --- |
| 250 | 100 | 4283 | 6253 |
| 500 | 300 | 4841 | 8530 |
| 1000 | 300 | 5939 | 9628 |
| 1000 | 1000 | 5939 | 15703 |

16000 gives more headroom than 12000 for these measured shapes and stays below
[GPT-5 mini's documented 128000 output-token limit](https://developers.openai.com/api/docs/models/gpt-5-mini).
This is a bounded mitigation, not an empirically tuned live-model guarantee.
Near-boundary quote-heavy output can still exhaust it, particularly with reasoning;
OpenAI's general experimentation guidance recommends a larger 25000-token reserve.
We retain the requested bounded module profile instead of raising all callers or
loosening the contract. Larger permitted schema extremes are not guaranteed to fit.

## Safe rejection diagnostics and verification

Rejections now include a closed response-status label, explicit usage container
and token field states (`missing`, `null`, `invalid`, `reported`), output-list
presence and counts of reasoning/message items and completed/incomplete/in-progress
item statuses. At most 32 items are inspected/counted, with a truncation flag.
Unknown provider labels become fixed safe labels. Numeric values retain the
existing budget/coherence bounds. No IDs, body, text, reasoning summaries, prompts,
evidence, credentials or arbitrary provider values are logged.

Regression coverage verifies exact CMO wire budget/schema, user-input isolation,
unchanged neighboring budgets, explicit zero versus missing/null/invalid usage,
bounded metadata, terminal incomplete rejection with one attempt and no downstream
job, and successful numeric-grounded CMO acceptance followed by EXPERIMENTS.
The enlarged daycare fixture has nine outputs, qualitative rationale and exact
age/price quotes throughout; its Unicode JSON measures 4802 visible tokens even
with only one parent per statement (the graph supplies eight).

No live provider generation was performed. Offline mocked-provider success proves
request selection, validation, acceptance and durable progression, not that the
production incident is resolved. After deployment, a separately authorized fresh
run should verify the same strict schema/model on the configured provider. If zero
usage incomplete recurs, compare safe usage states/item counts and investigate
provider/gateway capability/accounting; do not add retry, repair or fallback.

## Local validation (2026-10-12)

- Focused budget/response/CMO graph suite: 76 passed with disposable PostgreSQL.
- Full pytest with isolated PostgreSQL 15.19 and Redis: 2744 passed, 1 failed,
  zero skips (441.49 seconds).
- The failure is unchanged
  `test_release_hardening_postgresql.py::test_single_timeout_is_bounded_safe_and_never_starts_graph`:
  its 50 ms execution deadline cancels before the blocking mock provider is
  entered. It also fails in isolation and in a clean `git archive` of exact base
  `7f5b7cc479eef376fb13b964ee38302fe4c89798` with the same assertion. This is a
  demonstrated base/environment failure, not a green full-suite result.
- `compileall app bot` (and the sizing tool), staged diff-check, and `alembic check`
  passed; Alembic reported no new upgrade operations.
- Self-review and independent static review found no material findings.

No change to that unrelated timeout test or production timeout policy is included.
