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
