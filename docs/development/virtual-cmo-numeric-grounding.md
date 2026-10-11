# VIRTUAL_CMO numerical context

Base: `master` at `8e11a438d0ed4351656be6447d7b5e47408696f9`.

## Failure and execution boundary

The production failure class is `VIRTUAL_CMO / statement_semantics_invalid /
numerical_support_required`. Previously `IntelligenceExecutor` checked the whole
`statement.text`, and VIRTUAL_CMO checked each whole `statement.items` entry, by
substring membership in cited support. A Russian daycare recommendation containing
supplied ages and prices failed because the recommendation itself was new text.
Matching its individual numbers would incorrectly authorize new numerical claims.
The synthetic reproduction uses ages from two to seven, full/partial day monthly
prices, and an explicit profitability goal; no production response is retained.
The supplied historical log cannot identify which field failed: both paths emitted
the same module/stage/rule. The new server enum distinguishes text from items
(and quote context) without retaining or logging the provider response.

The path remains production Responses adapter -> exact request-scoped support
schema -> dispatcher -> VIRTUAL_CMO runtime validation -> normalized claims ->
Quality Gates -> PostgreSQL graph artifact -> presentation/downstream request.
PostgreSQL owns graph state. Numeric grounding is owned solely by
`executors/numeric_grounding.py`; shared validation for other modules is unchanged.

## Deterministic contract

VIRTUAL_CMO `text` and `items` contain qualitative strategy, without digits.
Numerical context is separate: up to three `{support_id, quote}` records per
statement, with quotes bounded to 1,000 characters. Generation requires
`numeric_context`, including an empty list. Its identities use the same exact
request-owned evidence/parent allowlists as statement support.

Runtime also requires that the quote's identity is cited by that same statement.
Each quote must equal one complete textual value/leaf of that particular local
first-party source, or the complete accepted parent's textual claim value. For
the authoritative structured CMO claim envelope, only complete summaries, items
and prior validated context quotes can propagate, never serialized JSON/IDs.
Other serialized parent structures cannot be interpreted as numerical assertions.
Nested first-party context is traversed without combining keys or leaves. Quotes
must contain digits and textual context; bare scalar numbers and number-only
strings cannot supply assertions. No substring extraction, punctuation/spacing
normalization, currency conversion, number-token matching, sentence splitting,
calculation, projection or cross-source combination is permitted. Long values are
omitted rather than truncated. This deliberately supports exact quotation, not
semantic paraphrase or general natural-language entailment.

Source goals and hypotheses can be preserved as quotes, not promoted into numeric
strategic conclusions. Site claims retain their complete qualifiers. The quote
channel adds no product-truth authority. Existing POSITIONING product-truth checks,
parent eligibility, exact IDs, support floors and confidence clamping remain.
Qualitative hypotheses still require their usual support; numerical quotation is
never proof that the surrounding recommendation is true or will meet a goal.

Quotes are included in the same normalized claim as the summary and items, before
outer acceptance/persistence. Public/Telegram sections show attributed quotes
without technical identities. A supplied numerical target can be shown only as
source context; the model cannot assert that its strategy achieves that number.

This is a stricter VIRTUAL_CMO generation contract, not a global relaxation.
One provider call remains one provider call: no executor retry, repair or fallback.
Semantic rejection remains terminal in the graph and creates no CMO artifact or
experiments job. Only server-enum `field=text|items|numeric_context` is added to
the existing module/stage/rule log. No indices, counts, source IDs, excerpts or
provider content are logged, and exposed exceptions remain content-free.

## Compatibility

Executor/binding and persisted payload version stay at v1. Existing stored outputs
without the optional field parse with `numeric_context=[]`; old artifacts are not
reprocessed. New provider schemas require the field. Newly generated numeric
strategy prose is intentionally rejected even if it equals a source: use an
explicit context quote instead.

The public strategy section adds optional `numeric_context: list[str]` (default
empty) containing presentation-labelled quotes. Backend and bundled Telegram DTOs
are updated together. Older external clients that forbid unknown fields need a
coordinated client update. No database schema or migration changes are needed.

## Regression evidence

- `test_virtual_cmo_numeric_grounding.py`: original Russian mismatch in both text
  and items; exact prices/ages; real gates; JSON round-trip; public and Telegram
  rendering; accepted parent hypotheses; site qualifiers; supplied numeric goals;
  invented numbers, same-number/different-assertion claims, calculations, projections,
  cross-source combinations, fragments, wrong/unknown/uncited identities; runtime
  bypass; scalar/length limits and old-payload reading.
- `test_virtual_cmo_numeric_postgresql.py`: real production composition and
  Responses wire with offline HTTP provider; strict schema object/identity checks;
  PostgreSQL artifact acceptance and fresh-service downstream reload; text/item/
  combination failures are terminal, with one call and no downstream artifact/job.
- Existing virtual CMO, exact support identity, intelligence, strategy graph and
  Telegram suites cover neighboring contracts. No live model evaluation is claimed.

Final validation:

- Full pytest with disposable PostgreSQL and Redis, both in the original checkout
  and an exact base-plus-staged-source snapshot: **2697 passed, 1 failed, no skips**.
  The failure is the unchanged
  `test_single_timeout_is_bounded_safe_and_never_starts_graph`: its 50 ms API
  deadline expires before the POST_GENERATION provider enters. The same release
  suite on the unmodified expected base reproduces it: **11 passed, 1 failed**.
  Isolated baseline/final-source executions passed, confirming timing sensitivity.
  The full suite is not claimed green; no unrelated timeout threshold is changed.
- Targeted migrations, common support matrix, existing production graph, numeric
  grounding and PostgreSQL selection: **72 passed**.
- Focused numerical/CMO/intelligence/exact identity selection: **122 passed**.
- `python -m compileall -q app bot tests`, working/staged `git diff --check`:
  passed. `alembic check` on disposable PostgreSQL: no new upgrade operations.
- Self-review completed; structured-parent JSON/technical-identity exposure was
  resolved and regression-tested. PR remains draft because full pytest has the
  reproduced baseline failure. No merge or live provider evaluation.
