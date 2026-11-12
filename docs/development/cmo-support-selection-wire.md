# CMO explicit support-selection wire

## Problem and architectural boundary

A real strategy run accepted all POSITIONING claims, then received a completed
CMO response that failed support_identity_invalid because a support array
contained duplicates. The old provider schema permits repeated array elements;
the strict canonical guard correctly rejects them. A separately authorized
provider feature check rejected uniqueItems, so this design does not introduce
that keyword or repair model arrays after completion.

The existing execution path remains Telegram -> authenticated Copilot -> durable
graph worker -> dispatcher -> VirtualCMOExecutor -> BaseExecutor -> provider.
PostgreSQL still owns Jobs, leases, accepted artifacts and history. The executor
owns only a request-local wire representation; it performs no persistence,
provider retries, routing, scheduling or additional provider calls.

## Versioned provider representation

VIRTUAL_CMO_SUPPORT_SELECTION_WIRE_ENABLED is a typed default-off setting, passed
through explicit production composition and the existing executor factory as
virtual_cmo_support_selection_wire / support_selection_wire. The wire version is
virtual_cmo.support_selection.v10. Neither Registry descriptors nor DTOs change.
Version 5 retains v2 selection semantics and adds the small observed-count
generation filter described in cmo-provider-semantic-contract.md. The v3
lookahead and v4 full-vocabulary candidates produced incomplete provider
responses and were not released. Persisted
canonical payloads and durable operation identities remain unchanged; a changed
generation fingerprint never authorizes replaying a completed provider POST.

The builder starts from the existing cmo_provider_schema contract, retaining its
qualitative text/items patterns and bounded exact same-source numeric pairs. It
also proves collapse of a retained single support branch before changing the
statement representation. Unknown shapes/references and schema-budget overflow
stop before provider I/O, with no permissive fallback.

outputs is a closed object with exactly request.expected_outputs as required
keys. It prevents missing/extra output names and does not contain output_name
inside statements. Shared main/other statement definitions retain original
text/items/assumptions/limitations/confidence/numeric_context bounds. The main
growth constraint remains HYPOTHESIS with one item; other statements retain the
existing HYPOTHESIS/RECOMMENDATION restriction.

Version 6 maps only the `risks` output to a dedicated closed statement definition.
Its RU/EN text/items describe prospective validation risks: compare audience
expectations, tested wording and confirmed owner terms; obtain an owner decision
before testing a proposed format; check resources before expansion. They do not
invent a personal/standardized/current feedback format, proven market position or
resource adequacy. Primary source selection, support maps, `numeric_context`,
kinds/confidence and all original string/array bounds remain unchanged. The other
eight outputs retain their existing free qualitative text/item schemas and the
frozen small generation filter.

Global `assumptions` keeps its original optional array and field bounds, but its
items are closed RU/EN validation prerequisites: validate working strategic
hypotheses before treating them as confirmed conclusions. This does not declare
all input evidence absent, deny supplied research/economics, or assume favorable
competition and available capacity. An empty assumption array remains allowed.
This is a deliberately narrower provider language; valid free-form risks or
assumptions outside these policies may reject. Canonical v1 artifacts/history and
original numerical, source-authority and product-fidelity checks are unchanged.

Canonical evidence_ids and parent_claim_ids arrays are absent and forbidden in
the wire. Instead each statement requires:

| Field | Meaning |
|---|---|
| primary_parent_key | One authorized parent alias when parents exist; otherwise null |
| primary_evidence_key | Null when parents exist; otherwise one authorized local evidence alias |
| additional_parent_support | Closed object with every parent alias required and strictly boolean |
| additional_evidence_support | Closed object with every evidence alias required and strictly boolean |

The untrusted source-data input contains support_selection_catalog with complete
parents/evidence mappings. p000/e000 aliases map bijectively to sorted authorized
source IDs. Existing scoped_facts/first_party_evidence and parent_claims remain
source authorities. Each namespace supports at most 128 choices; exceeding the
limit fails before the model, without truncating the allowlist or substituting
sources. Empty source families have empty closed boolean objects; no available
sources is invalid. Normal executor business/context checks still block first.

## Explicit citation semantics

Canonical citation set = primary source choice UNION additional true choices
UNION sources explicitly chosen by valid numeric_context support_id/quote pairs.
False in an additional map does not exclude primary or numeric-context citations.
A primary alias also marked true denotes the same typed-set member once. This is
an explicit wire meaning, not a malformed canonical array being deduplicated.

Every numeric-context pair must be selected verbatim from the same authoritative
bounded catalog used by the provider contract. The decoder never guesses an ID
from a quote, searches alternate sources, replaces a quote or changes strategy
prose. A numeric context is itself a first-class citation in this wire mode, so
its source contributes to canonical references, lineage, attribution and confidence.
Existing 64-entry/16KiB catalog limitations remain intentional generation bounds.

The decoder checks the complete wire schema and exact map keys/types, then emits
canonical outputs in request.expected_outputs order. It preserves model text,
items and quotations. Canonical arrays are formed from the selected sets; more
than 32 selected sources in either family fail the unchanged canonical bounds,
without truncation. Duplicate JSON keys fail at BaseExecutor's existing strict
JSON boundary before selection can hide a conflict. No missing map key is given
a default false value, and integer/string booleans are never coerced.

## Acceptance, compatibility and rollout limits

This is a declared provider/decoder protocol change, not equivalence with the
legacy structural schema or raw-response acceptance language. In particular,
selecting an exact numeric pair is an explicit citation under the new protocol;
legacy mode still rejects an uncited pair. The default-off mode retains its old
instruction bytes, model input, canonical-array representation and validation.
Only wire-enabled instances append protocol guidance; the class instruction is
unchanged.

The existing numeric catalog advice/binding flag is not enabled by this change.
When support-selection wire is active, legacy catalog advice and post-hoc binding
are bypassed even if the old flag was separately supplied. The typed decoder is
the sole mapping boundary. With the new wire off, existing catalog behavior is
unchanged.

After decoding, BaseExecutor independently validates the original canonical
schema and Pydantic type, then existing exact numeric quotation checks, source
scope, support floors, coverage, numerical rules, confidence and Quality Gates.
No guard is bypassed. Accepted storage remains virtual_cmo.payload.v1; old
artifacts stay readable. There are no migrations, history/state ownership changes,
router changes or changes to idempotency/restart behavior.

Boolean output size grows with requested outputs times available sources.
All 128 choices in each namespace remain representable, but the existing output
budget is unchanged; extreme scopes can leave less room for prose/reasoning.
Offline schema checks do not establish provider completion or marketing quality.
Live checks and rollout require a separately reviewed candidate; no live call or
production deployment is performed by this implementation.

## Verification

Focused tests cover the old duplicate-array gap, strict map encoding, all source
aliases and bounds, explicit primary/context/additional overlap, source floors,
same-source quotations, invalid pairs/aliases/booleans/missing/extra fields,
duplicate JSON keys, canonical overflow without truncation, original gates and
v1 serialization, partial requested outputs/order, ASCII/Unicode grounding,
confidence/attribution, default-off wiring and bytes, immutable schemas, provider
mutation, schema budgets/refusal, and the production HTTP adapter with mock
transport. Legacy uncited numerical context remains rejected. Two clean final
Telegram strategy workflows and qualitative acceptance remain separate gates.


## Version 9: productive qualitative language and prospective trade-off items

The v7 source-aware adjective trie with a terminal-separator wrapper and the v8
larger two-word trie with shared schema definitions both returned incomplete
actual CMO responses. Their receipts and FAIL outcomes are retained; local regex
validity and supported schema shapes did not establish provider completion.
V9 removes those generation-only catalogs, reference definitions and helper
modules, restoring the exact pre-refactor qualitative-generation implementation.
The original 959-character pattern retains UTF8 SHA256
`8cfe49afdb10b8f2319c466edc169619c93b7bb5a01aa4f0a88400cab042103c`.
No descriptor filter or terminal-separator requirement applies to free prose.
This is a bounded rollback candidate, not a proven provider root cause or fix.

V6's closed risk text/items and global hypothesis-validation assumptions remain.
Only `trade_offs.items` additionally uses a small RU/EN enum of prospective
trade-off policies: balance validation speed with faithful owner description,
choose further audience research or a bounded communication test based on results,
and compare proposed emphases while weighing clarity against completeness.
These are operator decisions to investigate, not asserted current delivery
formats, available assets, resources, completed approvals or proven efficacy.
The dedicated CMOTradeoffsStatement clones every other OtherStrategyStatement
field exactly. Items retain their original 1..3 array bound and 1..300 character
string bounds. Kind, confidence, support flags and numeric_context are unchanged.
Its text remains case-specific qualitative prose up to 4000 characters; the
remaining seven outputs keep their original qualitative text/items language.
Partial requested-name objects and all source bounds remain unchanged.

This representation loses some case-specific detail in trade-off items while
preserving an unrestricted strategic summary. It prevents the observed unsafe
format comparand in that item position; it does not guarantee the same premise
cannot appear in another free field. The strengthened canonical owner/demo,
standardized-format and numerical guards remain authoritative across all leaves.
A complete supplied standardized owner quotation in the free summary still
requires its actual selected local owner source. An uncited owner source, demo
or strategic parent hypothesis cannot authorize it. Supplied quantities remain
only complete exact numeric_context pairs under the original citation semantics.

No v7/v8 compatibility shim, stored-payload rewrite or source-flag repair remains.
Canonical payload v1, accepted history, durable operation IDs and persistence do
not change. A changed generation fingerprint never authorizes repeating a prior
POST. Independent code review and one fresh full normal CMO capability/content
proof are required before another full graph; HTTP 200, partial output, or old
successful responses do not substitute for that proof.


## Version 10: explicit whole-source selections

A completed v9 response appended interpretation to a demonstration assertion and
selected no local demo evidence on that output. Canonical fidelity correctly
rejected it. More prose guidance does not make source copying deterministic.
V10 gives free statement text/items a small explicit SOURCE:eNNN alternative.
The other alternative is the exact existing bounded 959-pattern string schema.
Markers contain ASCII digits, so these alternatives are disjoint without a new
regex or wrapping ordinary prose in mode objects. Schema enums contain only
marker keys; the model input separately labels complete supplied text, evidence
alias and source role. Source text remains untrusted data, never instructions.

The request-local CMO adapter uses the existing eNNN alias bijection. Eligibility
queries canonical typed_literal_sources, the pure implementation used unchanged
by selected_sources: FIRST_PARTY product_truth/confirmed_business_fact are owner
sources; FIRST_PARTY existing_proof is demo evidence. Audience/external/parent
hypotheses are not selector sources. No POSITIONING product/RTB catalog authority
is imported. Only complete nonempty string values up to 4000 characters that
contain no canonical numerical quantity or reserved SOURCE namespace are offered.
No structured-value extraction, sentence splitting, trimming or truncation occurs.
Outer-whitespace-padded values are omitted/refused, never trimmed: the existing
canonical Pydantic policy strips outer whitespace, so such a value could not
remain an exact accepted source quotation. Interior spacing/newlines stay exact.
The complete expanded value must also match the frozen qualitative language;
SOURCE never bypasses its observed-count-word restriction. This deliberately
omits even supplied unlisted-unit `two principles` or a brand containing the
standalone word `Two`, without claiming general quantity entailment or repairing
the source. The original canonical numeric detector remains independent.
Item enums include only markers whose full expanded value fits 300 characters.
Numerical values remain exclusively in the original numeric_context mechanism.
At most 64 selector entries and 16384 UTF8 JSON bytes are allowed; overflow fails
before model I/O. Original aggregate schema/source limits apply independently.

Encoding, model input and decoding materialize the same evidence tuple and
reconstruct the same scoped catalog and aliases. Decoding validates wire JSON,
then resolves only an exact explicit marker to one complete source value and
adds that actual evidence ID to the SAME output's canonical selected set. This
is declared explicit selection, like primary/additional/numeric_context choices:
a false additional flag does not veto a SOURCE choice. Raw booleans/input are
never changed. Ordinary prose is never matched to source text, shortened, split
or repaired. Rendering happens once; supplied source values containing reserved
syntax are omitted/refused, not recursively interpreted. All canonical schema,
Pydantic, kind, owner/demo/equipment/numeric, 32-source and QG checks still run.
A demo selector cannot authorize an owner-format claim, and a source selected on
another output cannot repair a missing witness here.

Only free statement fields receive selectors. Closed risk fields, trade-off
items and global assumptions/limitations never render them. The SOURCE:
namespace is case-insensitively reserved: unknown/malformed, concatenated,
wrong-size or out-of-scope markers reject instead of leaking as literal prose.
There is no fallback source lookup or fuzzy correction. The schema and decoder
retain original 4000/300 bounds and partial-name scope. The canonical payload is
still v1 with plain text and actual source IDs; no selector or catalog persists.

The producer can quote via SOURCE and place interpretation in another free leaf.
It may still choose unsafe ordinary prose, which must continue failing canonical
validation. The original nu FAIL stays immutable. Offline known-response and
mock-HTTP tests establish the explicit rendering contract only; independent code
review and a fresh complete nine-output normal capability/QG/content check are
required before another full graph. A provider POST is never replayed because a
wire version or instruction fingerprint changed.
