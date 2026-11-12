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
virtual_cmo.support_selection.v8. Neither Registry descriptors nor DTOs change.
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


## Versions 7 and 8: source-aware format generation subset

A completed response moved an unconfirmed standardized-feedback premise from
`risks` into free `trade_offs` prose. The canonical owner guard correctly rejected
it. Versions 7 and 8 keep the eight non-risk outputs case-specific, but restrict their
free text/items and global limitations with a small regular generation language.
It excludes the observed RU personal/individual/standardized descriptor families
and EN personal/personalized/personalised, individual/individualized/individualised,
standardized/standardised words. This deliberately also narrows legitimate
adjective questions and negative warnings: rephrase those using other qualitative
words. It is not general factuality checking or a canonical ban.

The shared finite trie complements exact words and prefix families without
lookaround, backreferences, Unicode shorthand or internal anchors. Version 7 used one trie copy and required generated words to finish with a
separator. Its actual full CMO response was incomplete; the captured unfinished
leaf could still be completed locally, so a causal decoder explanation is not
established. Version 8 restores the established outer-only two-word wrapper over
the same attribute/count trie: generated prose may end in an ordinary word.
This changes only the provider generation subset, not canonical history.
The server does not append punctuation or repair source flags. The original
two-count language used by legacy CMO and EXP stays exactly 959 characters with UTF8 SHA256
`8cfe49afdb10b8f2319c466edc169619c93b7bb5a01aa4f0a88400cab042103c`.
Canonical validation/history never acquired the v7 terminal-separator restriction.

An alternative enum permits complete actual owner quotations that contain a
filtered descriptor. Its catalog comes only from the executor's request-local
FIRST_PARTY `product_truth`/`confirmed_business_fact` evidence, using complete
string values exactly as the canonical owner witness does. No structured leaf
extraction, partial quote, ordinary-prose escape or role inference is allowed.
Numerical values stay solely in numeric_context. Whole values over 4000
characters are omitted; the item enum includes only complete values up to 300.
At most 64 entries and 16384 UTF8 JSON bytes are allowed; overflow rejects rather
than silently truncating. Existing schema-wide limits apply as well.

Schema generation and decoding reconstruct the identical catalog from the same
request evidence. When a leaf uses the owner-quote alternative, decoding requires
an explicit already-selected evidence ID for that exact quote. It never adds a
citation or changes a flag. The normal canonical owner/demo/numeric guards still
run afterwards. Demo, audience, external and HYPOTHESIS sources do not authorize
this enum; unscoped assumptions/limitations never receive an owner alternative.
Closed risk and assumption policies remain unchanged. Numeric-context selection,
source bounds, mandatory parent selection, partial-output scope, canonical v1 and
persisted artifacts remain unchanged.

Local contract checks do not prove provider completion. Before another full graph,
a fresh bounded normal CMO diagnostic must complete all nine outputs and pass
wire, canonical, semantic, quality and independent content review. HTTP 200,
schema acceptance alone, empty or partial output are not successful proof.


Version 8 also stores the 8457-character/10875-byte CMO pattern exactly twice in
reserved bounded string definitions: CMOQualitativeText (1..4000 characters) and
CMOQualitativeItem (1..300). Free statement fields reference these definitions;
owner-quote enums remain separate anyOf alternatives, and global limitations
reference the same text definition without a quote alternative. Field title and
description annotations remain at the original field location. Each `$ref` node
is bare. When a field has annotations but no owner quote alternative, a one-branch
`anyOf` surrounds the reference and holds those annotations; owner-enabled fields
already use an outer `anyOf`. No `$ref` siblings rely on SDK normalization or
cause implicit inlining of the shared patterns. Definition name
collisions, unknown source shapes and existing aggregate schema-budget overflow
fail before provider I/O. This avoids five repeated copies of the larger regex,
even when owner quotes are available. Fewer schema bytes do not establish reduced
provider decoder complexity or completion. V8 is a joint representation candidate,
not a proven root cause or successful provider fix; the failed v7 receipt stays
immutable, and a fresh full normal CMO capability/content proof is still required.

The support-branch collapse occurs before v8 prose references are installed.
`VirtualCMOExecutor.provider_schema_for` copies the completed wire schema;
`production_model_call` passes it as `response_format.schema`, and `chat` places
that same schema into `text.format.schema` before `httpx.AsyncClient.post`.
There is no later single-anyOf collapse, SDK schema normalization or reference
expansion on this manual HTTP path. Mock-transport regression coverage inspects
the actual transmitted schema for equality, exactly two patterns and bare refs.
