# VIRTUAL_CMO catalog numeric citation binding

## Safety and contract analysis

Baseline: master `1a0ab10` (PR #118). Reported isolated catalog replay payload
SHA-256: `9e240cc4e3f17034b5a5c6352f6ab93d6410ed556982b5073fea7a5b0dca82a8`.
One provider call failed at `statement_semantics_invalid / numerical_support_required /
support_not_cited`, output index 1, numeric context index 0; Quality Gates were not
run. The historical raw response is unavailable. Synthetic offline regression
reproduces this failure class; it does not prove the precise historical quote.

Before implementation, trace: production Responses adapter -> BaseExecutor.generate
strict JSON parsing -> request-scoped JSON Schema -> Pydantic -> VIRTUAL_CMO
build_result -> shared support validation -> numeric_grounding -> normalized
provenance/confidence -> outer Quality Gates -> graph persistence. PostgreSQL
owns graph state. This change owns no durable state and performs no I/O.

Authoritative source scope remains `scoped_facts`/`first_party_evidence` and
`parent_claims`: authorized nonempty local facts and PASS/PASS_WITH_LIMITATIONS,
WITHIN_SCOPE supplied parents. Quotation authority remains exclusively
`context_units`/`parent_context_units`; no new quotation extractor or evidence
search is introduced. The catalog remains bounded input advice, not authority.

Risks identified before implementation: forging references by textual similarity;
source-family confusion; laundering website assertions; rescuing missing strategic
parents; overflowing citation arrays; changing confidence or bypassing gates;
Pydantic stripping quote/ID whitespace. These require exact checks against raw
model JSON, original schema checks before binding, unambiguous source ownership,
bounded append-only changes, and rerunning the existing validation pipeline.

## Explicit change to server acceptance policy

This is an intentional expansion of server acceptance in experimental catalog mode,
**not equivalent to the prior contract**. When
`VIRTUAL_CMO_NUMERIC_QUOTE_CATALOG_ENABLED=true`, an otherwise valid response may
omit a repeated citation ID from its statement if it already selects that exact ID
in numeric_context.support_id and copies one complete eligible textual unit from
that same scoped source verbatim. The server appends that ID to evidence_ids for
local evidence or parent_claim_ids for accepted parent claims.

The raw response must first pass the original JSON Schema and Pydantic validations,
including an existing nonempty parent citation on every statement when scoped
parents exist. Numeric context cannot supply the missing mandatory strategic
parent or rescue empty support arrays. Additional numeric parents can be bound
only alongside the already explicit strategic support.

Binding examines raw JSON quote/support_id, before Pydantic whitespace stripping
can affect the comparison. It never searches other sources for matching text or
numbers. Unknown/out-of-scope IDs, cross-family collisions, fragments, changed
digits, units or qualifiers cannot be bound. An exact quote from a different
source does not authorize the selected ID. Eligible quotes excluded from the
bounded input catalog still use the same authoritative source checks.

Each statement's additions are atomic: a context with an ineligible source/quote,
existing duplicate references, or additions exceeding the existing per-family
32-reference bound leaves that statement untouched. Invalid responses continue
through the original pipeline and fail closed. Existing citations and their order
are preserved; repeated numeric contexts cause at most one appended ID per family.
No quote, support_id, strategy text/items, kind or confidence is repaired.

The exact same request-scoped JSON Schema and Pydantic checks run again on changed
payloads. Original support identity/coverage, numeric semantics, provenance and
Quality Gates remain authoritative. Binding does not imply acceptance. Existing
downstream confidence clamping runs with all cited supports, so adding lower
confidence support can lower the result ceiling. Hypotheses/recommendations remain
at most MEDIUM. Newly cited parents also contribute existing lineage and inherited
assumptions/limitations in gates. Site attribution continues through the original
source-based `context_attribution`, including inherited site claims and unknown
legacy/conflicting attribution. Contextual numbers gain no assertion authority.

With the flag false (the unchanged default), normalization returns the original
payload and the entire provider wire and prior rejection behavior are unchanged.
Provider prompts/schema/model/token budget are unchanged in both modes. This
policy adds no model calls, retries, repairs or fallback. Baseline replay uses the
old acceptance policy; catalog replay uses this opt-in server policy with its
existing separately approved payload fingerprint. Identical provider wire hashes
do not identify the server acceptance policy version; record the build HEAD.

## Diagnostics and compatibility

INFO log: fixed `module=VIRTUAL_CMO code=numeric_context_citation_bound` and
`normalized_reference_count` (number of new statement/source reference edges for
this response, at most 27). No IDs, quotes or business values are logged. The count
means bindings applied **before** final validation/gates, not accepted links. No
event is emitted when zero bindings are applied. The replay CLI disables logging
as before; its booleans still reflect full validation and gates, not this count.

No DTO, persisted schema, version, migration or production flag changes. Stored
artifacts are not rewritten; new accepted results persist the augmented citation
arrays via existing contracts. Rollback disables the experimental flag for future
executions; already accepted artifacts retain their lineage. This change performs
no deploy or live provider calls. Deterministic checks cannot establish model
quality or the acceptance of the unavailable historical response.

## Regression coverage

`test_virtual_cmo_numeric_binding.py` uses mock HTTP through the production adapter,
registry and dispatcher: exact missing and explicit citations, idempotence/no
duplicates, source-scope/unknown/wrong IDs, raw whitespace, full array limits,
mandatory parents, numeric prose/items/kinds/constraint bounds, site attribution,
confidence ceilings, identical gates and disabled full wire. Helper tests prove
only evidence_ids/parent_claim_ids change and no cross-source matching occurs.
`test_virtual_cmo_diagnostics.py` exercises baseline/catalog replay with one POST,
original gates (including rejection), unchanged wire and content-free reports.
Existing numeric grounding, graph, parent boundary and executor suites cover
neighboring strategic restrictions and failure stages.
