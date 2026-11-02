# POSITIONING explicit text modes

The internal support-selection wire is now `positioning.support_selection.v4`.
Each output's `text` is a disjoint tagged object with exactly `mode` and `value`:

- `QUALITATIVE`: new prose using the existing simple ASCII-digit-free assertion pattern.
- `SOURCE`: an entire bounded assertion from the existing literal source enum.

The decoder validates the complete v4 wire first, copies it, and assigns the
selected `value` to the canonical string. It never guesses a mode, edits text,
adds punctuation, infers a citation, or accepts a v3 response as v4. Both branches
retain the same literal/string constraints, source catalogs, canonical provenance,
numeric, RTB, assurance, product, kind and Quality Gates checks. Selecting SOURCE
does not establish source authority. Missing/oversize sources remain unavailable;
no source is truncated or synthesized. Schema bounds still apply after wrapping.

This is an internal producer representation change behind the existing default-off
POSITIONING_SUPPORT_SELECTION_WIRE_ENABLED flag. Canonical persisted payloads and
history readers remain v1; public DTOs, models, token budgets, retries, graph
ownership and migrations are unchanged. Cutover drains active and pending work;
new executions use v4. Saved results use existing canonical readers.

Motivation: both exact-cardinal and prefix-pruned string unions stopped before
the first text character in a full restored synthetic workshop request, despite
valid continuations and output far below the token cap. Candidate21's sole POST
req_81c231d7a6ba4dae9dd9ae7b6809a735 returned incomplete after395 output tokens
against16000. A minimal regex-plus-enum compatibility case completed successfully
(req_71ca88f4b8b9440ea229c01548c4abc2). These observations do not establish the
provider's internal cause. Disjoint object modes are a testable simplification;
actual restored-context probes and full CI remain deployment gates. No failed
response was repaired, persisted, retried automatically or counted as acceptance.

Regression coverage includes both modes, raw immutability, unchanged canonical
validation, literal numeric text without final punctuation, invalid/unknown modes,
missing/extra fields, legacy v3 rejection and absence of unavailable source mode.
Existing source-authority and unrelated-category rejection tests use explicit
SOURCE values, so wrapping cannot make them pass by accidentally failing syntax.

The initial tagged/full-vocabulary candidate also stopped early. The final producer
therefore retains explicit modes but removes finite-word grammar from provider
syntax. In isolated diagnostic generation with the unchanged full canonical guard:
course req_ad2ba253d59f4085a1bf9313ed7310e8 and workshop
req_edb1e70cf83a4c42a82f1f4dfa6cb64d both completed and passed strict validation,
Quality Gates and literal cited RTB. They are isolated proofs, not final Telegram
acceptance. The exact final-image payloads must match these proofs before deployment.

A regression also exposed an unrecognized introductory modifier in counted
phrases. The shared finite modifier list now includes introductory and вводный
inflections; its algorithm, units, source-authority and word-gap bounds are
preserved. Previously successful saved responses must be revalidated with this
stronger guard before their proofs are reused.
