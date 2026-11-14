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

## Audience selection in support selection v7

A live v6 response selected a demonstration task for target because the
provider schema shared the general SOURCE enum with other outputs. The
decoder rejected the response. In v7 the target SOURCE alternative lists
only complete supplied audience assertions. It is absent when the request
has no eligible audience assertion. QUALITATIVE remains available for
audience hypotheses and neutral strategic text.

## Claim plan in support selection v8

The executor builds a request-local plan from complete supplied product
conditions and supporting material. Each entry retains its exact text on the
server, its evidence identity, source category, authority and allowed outputs.
Supporting material can substantiate RTB and cannot become an offer or a
product condition. Strategic sections such as differentiation select their
own text and support separately.

The provider receives only the metadata of product plan entries. Product
detail values are removed from both copies of the direct evidence in the
generation input. The model can choose eligible keys and draft useful
strategy from the product description, audience and other authorized
context in one request. Decoding a selected key resolves its exact text and
evidence before canonical and semantic validation. The strategy can still
contain unsupported assertions inferred from other context, so live semantic
and human review remain necessary. Keys with identical metadata cannot be
ranked by textual relevance by the model.

Persisted canonical results keep the same schema. Raw v7 replies require
the v7 revision for replay.

## Role-separated strategic drafting in v9

The product truth text is present once in the claim plan. Its evidence
identity and supplied authority are unchanged. Supporting material stays
opaque to the drafter and can only be selected for RTB.

The provider schema reserves product quotation for offer and RTB.
Value proposition, positioning statement and message hierarchy require
qualitative hypotheses or recommendations. Each can use the factual basis
through its selected support. The decoder still verifies the closed
source keys and the existing canonical and semantic checks still run.

This boundary prevents replacing a strategic section with a product quote.
Review of the complete draft remains necessary for unsupported assertions
in qualitative language. A second live verification call inside the same
graph node would violate Responses retry governance after a successful
receipt. Production verification would need an explicitly budgeted durable
stage with its own recovery and provider-call identity.

## Durable verification rollout

Enable POSITIONING_DURABLE_VERIFICATION_ENABLED with
RESPONSES_WORKFLOW_GOVERNANCE_ENABLED only after migration 20261103_0014.
New runs record the verifier contract at creation. Existing runs keep their
original contract. Every POSITIONING completion in a marked run requires a
verified checkpoint matching the canonical result.

Private positioning_verifications rows belong to a Job and are outside
MarketingArtifact. The Responses reservation remains on the run. The completed
receipt and bounded response text commit together under the run, lease and Job
fence. Replacement workers recompute the request fingerprint before replaying
the response, and repeat deterministic decoding. A saved canonical draft and
its evidence are fingerprinted before the independent verification call.
Verification uses a distinct operation in the same workflow budget with a
single reservation. A reserved or unknown request with no saved response
blocks replay. The worker records the verification decision before Quality
Gates. Only normal artifact finalization releases graph dependencies.

A verifier can miss an implicit assertion. Independent approval and the
deterministic contract are both required, and this release still requires
manual quality acceptance. Unstructured legacy product evidence does not
provide a typed follow-up constraint. No automated remediation is enabled.
