# POSITIONING explicit source selections

A single immutable-image diagnostic on 4a49004 returned complete JSON but was
rejected: points_of_difference.evidence_ids contained three entries with only two
unique identities. The original response was preserved, not repaired, accepted
or retried. Canonical duplicate-reference rejection remains in both modes.

The default-off POSITIONING_SUPPORT_SELECTION_WIRE_ENABLED gate uses provider-only
positioning.support_selection.v3: exact requested output keys, a mandatory
primary_support_key and closed boolean evidence_support/parent_support maps.
Catalog aliases are complete deterministic bijections over the original scoped
sources. Product outputs select primary local product_truth/existing_proof;
other outputs may select either evidence or accepted parents. All materially used
sources must still be selected explicitly. A primary/additional overlap means one
set member; no model citation arrays exist in this wire format.

The builder requires equality with the exact regenerated canonical schema before
transforming it. Text/kind/confidence/assumptions/limitations constraints remain;
the source support OR becomes a mandatory scalar choice. Unreviewed canonical
shapes fail before dispatch. Decoding does not rewrite text, infer sources from
content, truncate choices or remove duplicates from model arrays. Original JSON
Schema, Pydantic, output coverage, 32 references per family, numerical support,
RTB/assurance/observation semantics, normalization and Quality Gates still run
after mapping. Over-selection can fail the canonical bound; it is never trimmed.

Reuse the existing 250-per-family catalog contract and 2048 required boolean flag
preflight. Extreme scopes fail rather than losing sources or increasing budgets;
schema admission does not guarantee every request fits the output token budget.
This wire is incompatible with the older product-support wire and minimal schema
experiment; the equivalent schema projection flag can coexist. Production
composition forwards a strict boolean, default false. Stored canonical payloads,
old readers, DTOs and migrations remain unchanged. No historical artifact is
retroactively certified. This change does not establish semantic truth of supplied
facts; manual business quality review remains required.
