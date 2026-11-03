# RTB generation selects actual product/proof assertions

Fresh Telegram run9aecf981… on a88218d failed once before artifact persistence.
A single GET of its existing response (originalPOSTreq_7e4054fe69d54502b7c220ac6d3fdf59,
GETreq_ca54cfe5ea7a40f5b220fb294f118940) recovered unchanged raw data into the
approved private directory. Retrieved/captured provider schemas match exactly;
JSON, provider, wire and canonical schemas pass. Exhaustive validation of all16
statements found only RTB/output9/rtb_quote_required. The response was not repaired
or retried; it is not an acceptance success.

For requested RTB, the internal v4 provider text now requires SOURCE mode and an
entire bounded local product_truth/existing_proof assertion. Other context and
parent assertions stay available to other outputs but cannot be proposed as RTB.
Empty/oversize-only proof fails before POST; nothing is truncated or extracted.
The provider instructions explicitly require this mode and the actual citation.

The decoder still copies the chosen value unchanged. Selecting a literal does
not infer a citation: actual selected-source, product/RTB/numeric/assurance/kind
and Quality Gates validation remain authoritative. Existing canonical RTB accepts
supported contiguous quotations; the producer is deliberately narrower, choosing
complete source values. This changes no canonical schema, DTO, storage, migration,
model, retry policy, budget or default-off rollout flag. Partial requests without
RTB retain their previous text alternatives. Full schema bounds still apply.

Four new regressions fail on the old wire; six new cases cover excluded free mode,
other-category/parent sources, exact product/proof quotes, raw immutability and
missing/oversize refusal. Full CI and both live restored-context probes remain
mandatory deployment gates; fresh final Telegram acceptance restarts after fix.

## Product facts beyond RTB in support selection v6

The provider receives the request's bounded product_truth and existing_proof
assertions as a catalog. A SOURCE choice of a product key selects its whole
assertion and evidence identity together. Identical wording in two eligible
sources has two keys. A raw literal or a legacy quote alias cannot substitute
for a product key. RTB remains restricted to this catalog. The target output
rejects a product key.

QUALITATIVE remains available for strategy and uncertainty. The decoder
rejects an exact product assertion submitted as free prose. Canonical
validation, semantic validation and Quality Gates still run on the decoded
result. Semantic checks and human review remain necessary for paraphrases,
unsupported product details and competitive conclusions in free prose.

The change is limited to the existing support selection rollout path.
Persisted canonical results use the same schema. Replay of raw v5 responses
requires the v5 revision.
