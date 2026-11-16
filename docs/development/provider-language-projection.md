# Provider language projection (CMO, EXPERIMENTS)

Status: implemented for Russian requests, provider-only. Module:
`app/module_execution/executors/provider_language.py`.

## Why

Multi-domain live acceptance on `196cb37` (15.11.2026, five cases, see
`acceptance-progress.md`) passed technically in four of five graphs but was not
accepted semantically:

- Russian requests received mostly English CMO prose (pre-existing: the closed
  recipes exist in Russian and English and nothing bound the output language);
- prose started with kind labels or field names (`HYPOTHESIS: …`,
  `target_metric: …`); the wire v17 stem guard turned them into «Hypnosis:»,
  «RECOMENDATION:», «HYPOT HYP:»;
- EXPERIMENTS wrote «двухвариантных текстов»; the numeric guard treats a
  cardinal+unit compound as a quantity, the generation pattern forbade only whole
  count words, and the node failed with `NUMERICAL_SUPPORT_REQUIRED`.

All three are generation problems. They are closed where generation is
constrained, not by weakening a validator.

## What the projection does

`language_projection(schema, request)` is applied in `provider_schema_for` of
VIRTUAL_CMO and EXPERIMENTS (support-selection wires only). When the owner's own
inputs (objective, constraints, authorized facts) are predominantly Cyrillic:

1. free-prose patterns are replaced by Cyrillic-only patterns: a word consists of
   Cyrillic letters and separators are a positive list of ordinary punctuation and
   the space, so Latin letters, digits of any script, `_` and other symbols cannot
   be generated. (A negated separator class admitted Arabic-Indic digits: on
   `6778cd7` the model wrote a time as «۱۸:۰۰» and the numeric guard rejected it.);
2. the count stems `двух`, `трёх`, `трех`, `четырёх`, `четырех` are forbidden as
   word prefixes (the whole compound family, matching the numeric guard); demo
   vocabulary is closed in EXPERIMENTS prose as it already is in CMO prose (on
   `33e6918` the model embedded the owner's demo sentence in a longer text and the
   node failed with `DEMONSTRATION_ASSERTION_REQUIRES_SOURCE`);
3. closed server sentences that come in translated pairs keep only the Russian
   member; relation keys keep only the `_ru` member;
4. the model input carries `output_language` and a one-sentence guidance.

Other request languages get the unchanged schema.

## Guarantees

- **Narrowing only.** Everything the provider can generate is valid for the
  unchanged wire schema; the decoder, canonical v1, downstream fidelity checks and
  Quality Gates are not modified. The projection is not a safety control: the
  server still validates the superset.
- **Owner texts are never removed.** A value that occurs anywhere in the request
  (facts, constraints, quotes, upstream statements) is never a removal candidate,
  and a sentence is removed only as the English member of a complete translated
  pair. If a projected array could not satisfy its `minItems`, the unprojected
  schema is sent.
- **Provider compatibility is pinned.** The provider answers an unsupported
  pattern with an empty `incomplete` response; offline tests cannot see that.
  `tests/test_provider_language.py` pins the SHA-256 of both patterns after probe
  `req_d32ef29ee0984035a6a5b148829d221d` (CMO) and
  `req_62cf3c1513b7423da48279f0723fa9be` (EXPERIMENTS). Changing a pattern requires
  a new probe.

## Trade-offs and limits

- Russian free prose cannot contain Latin brand or channel names, abbreviations
  such as «A/B» or any digit; the model must use Russian spelling or a description.
  Owner texts with Latin names still appear through SOURCE/TERMS choices and
  quotes.
- English requests keep the wire v17 label stems and therefore the garbled-label
  risk observed on `196cb37`; an English-bound projection is not implemented.
- Partial restatement of owner terms in free prose (finding D4 of the acceptance)
  is not addressed here.

## Owner sentences: exact or not at all (16.11.2026)

Production acceptance on `91a0589` accepted, in three runs of three, a misspelt copy
of the owner's demonstration sentence in EXPERIMENTS `minimum_required_inputs`
(«Есть демонтрационный образец…», «…из трё х видов хлеба»). The executor
instruction asks for the complete verbatim `existing_proof` sentence there, but the
Russian-bound free prose cannot spell it (demo vocabulary and count compounds are
excluded). The model wrote the nearest spelling the grammar allowed, and no lexical
rule recognized the result. Offline replay confirmed all three parts: the exact
sentence is accepted, the misspelt one was accepted too, an extended one is rejected.

Three changes, none of which relaxes a check:

1. **Exact choice (provider schema).** `required_input_source_choices` adds the
   request-local first-party `existing_proof` sentences as a closed branch of
   `minimum_required_inputs` items (`AllowedExperimentRequiredInputSource`), next to
   the unchanged free-prose branch. Only sentences the unchanged wire schema already
   accepts are listed, so the narrowing property above still holds. Because the free
   branch cannot continue past «демонс…» or a count compound, an item that starts as
   the owner's sentence can only be completed as the exact sentence.
2. **Distorted copies are rejected (validator).** `reject_distorted_source_copy`
   compares every generated CMO and EXPERIMENTS leaf with the request-local
   first-party owner sentences (`product_truth`, `confirmed_business_fact`,
   `existing_proof`, constraints). A leaf that is at least 0.9 similar to such a
   sentence without being it, and without containing it verbatim, fails with the
   existing rules (`demonstration_assertion_requires_source` /
   `product_claim_requires_truth`). The comparison needs no vocabulary and no domain.
3. **A misspelt demo word is still a demo word (validator).** `mentions_demo` adds
   `distorted_demo_mention` to the exact-stem check, so «демонрационный образец
   подтверждает…» is judged like its correct spelling. It only recognizes; it grants
   nothing. A misspelt reference without an assertion is not made fatal.

The guidance sent with Russian requests now names the neutral reference
«предоставленный образец» and the exact-choice rule.

Unchanged on purpose: the nested-source ownership contract. An exact sentence that
states what the demo shows («…который показывает сравнение снимков») is still
accepted only when the model selects that source on the first output
(`test_named_basis_owns_nested_sources_independently_of_model_order`).

Known consequences and limits:

- Outputs that passed only because of a misspelling are now rejected. Replayed
  against the changed validator, the production course run of 16.11.2026 fails in
  VIRTUAL_CMO (two leaves: a misspelt demo word next to «показывающей» /
  «существующий») and in EXPERIMENTS; bakery and grooming fail only on the distorted
  sentence that the exact choice now replaces. Whether the model follows the new
  guidance can be established only by live runs.
- The demonstration rule itself stays a lexical co-occurrence check: «существующий
  демонстрационный образец» and an unrelated verb in another clause are rejected
  like real assertions. Refining it is a separate decision.
- Free CMO prose still excludes demo vocabulary (wire v17), so a misspelt reference
  without an assertion can still appear there.
- Degenerate repetition after a blocked digit («заказ принимается до я я я…»,
  observed on `33e6918`, not on `91a0589`) is not detected.
- The anyOf of a pattern branch and an enum reference inside array items is the
  structure the statement texts already use live; it has not yet been probed for
  this field.
