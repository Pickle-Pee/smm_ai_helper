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
virtual_cmo.support_selection.v2. Neither Registry descriptors nor DTOs change.

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
