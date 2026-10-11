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
PostgreSQL owns graph state. Numeric context validation is owned by
`executors/numeric_grounding.py`; persisted parent decoding is owned by
`executors/claim_support.py`. The shared numerical rule remains unchanged.

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

The PR #107 review reproduced downstream laundering at head
`07bdc3d5b70fe376b26c9287c4f98f4267bb0505`: after CMO gate acceptance and persistence,
`18 000 рублей` passed the old substring rule against the serialized parent JSON.
Both shared canonical statement validation and ExperimentDesign validation now
extract support through the same strict typed StrategyClaim boundary. It rejects
unknown fields, duplicate keys, wrong types and malformed structures. Structured
CMO claims expose only qualitative summary/items as assertion support; their
numeric_context is never assertion support. Plain accepted positioning assertions
retain their existing numerical authority. Time/resource constraints still must
exactly match genuinely supplied constraints. Unknown serialized structures fail
closed rather than becoming unrestricted support text.

Source goals and hypotheses can be preserved as quotes, not promoted into numeric
strategic conclusions. Site claims retain their complete qualifiers. The quote
channel adds no product-truth authority. Existing POSITIONING product-truth checks,
parent eligibility, exact IDs, support floors and confidence clamping remain.
Qualitative hypotheses still require their usual support; numerical quotation is
never proof that the surrounding recommendation is true or will meet a goal.

Quotes are included in the same normalized claim as the summary and items, before
outer acceptance/persistence. Public/Telegram sections show attributed quotes
without technical identities. Each stored quote additionally carries attribution
assigned by the server from its actual evidence input key, the owned-site projection's
structured `trust: site_claim` marker, or inherited contextual
quote. This metadata is absent from the provider schema and cannot be chosen by
the model. Site claims render as website assertions, explicitly not owner-confirmed,
even when the original quote lacks that qualifier. Legacy quotes default to unknown
attribution. A supplied numerical target can be shown only as
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
reprocessed. Stored claim attribution is optional for reading old envelopes; no
schema migration or identity change is required. New provider schemas require the
context field. Newly generated numeric
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
  PostgreSQL artifact acceptance and fresh-service execution of EXPERIMENTS;
  qualitative continuation succeeds, canonical/expected_signal laundering fails
  terminally without an experiments artifact or retry. Text/item/combination CMO
  failures remain terminal with one call and no downstream job.
- `test_cmo_parent_support_boundary.py`: a fully accepted, persisted CMO parent;
  fragments and whole contextual assertions rejected in canonical outputs and all
  experiment text fields; qualitative lineage/confidence preserved; strict malformed
  envelope rejection; site attribution preserved through subsequent CMO quotation.
- Existing virtual CMO, exact support identity, intelligence, strategy graph and
  Telegram suites cover neighboring contracts. No live model evaluation is claimed.

Review correction validation:

- Clean original-head reproduction: both canonical EXPERIMENTS text and
  expected_signal were accepted by execution and Quality Gates after laundering
  a fully accepted CMO context quote. Both are now rejected.
- Final focused parent-boundary, numerical grounding and intelligence selection:
  **97 passed**, including existing genuine numeric hypothesis/constraint coverage.
- Production-shaped PostgreSQL POSITIONING -> VIRTUAL_CMO -> EXPERIMENTS:
  **6 passed**, with accepted qualitative continuation and terminal laundering
  rejection, one provider call per node and no retry/repair/fallback.
- Full pytest and exact-head CI results are recorded in
  [PR #107](https://github.com/Pickle-Pee/smm_ai_helper/pull/107).
- Compileall, staged diff-check and disposable PostgreSQL Alembic check passed.
- Self-review resolved the structured owned-site trust-marker attribution case.
  The typed boundary preserves exact quote bytes, rejects malformed envelopes,
  excludes contextual numbers from assertion support, and retains accepted
  identities, confidence, lineage and product-truth authority. No merge.
