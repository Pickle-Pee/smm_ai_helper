# EXPERIMENTS explicit additional support sets

## Confirmed boundary and compatibility

A production response was JSON-valid and passed the exact provider/V2 wire schema,
but the original decoder rejected repeated parent references at outputs 6, 9 and
13. Each malformed array contained two references to one source. This was confirmed
by read-only recovery of that existing response and offline validation in its old
immutable image; no additional provider POST was used. The strict rejection is
correct and remains. The saved response is never repaired or accepted retrospectively.

EXPERIMENTS_SUPPORT_SELECTION_WIRE_ENABLED is typed and default false. The executor
option is support_selection_wire; enabling it requires strategic_parent_wire=True.
Production composition passes both explicit settings. With the new flag off,
existing V2 schemas, model-input bytes, instruction bytes and duplicate rejection
remain unchanged. Persisted storage remains experiments.payload.v1; old artifacts
and history readers need no migration.

## Declared provider protocol

The current version is experiments.support_selection.v5. It is built on the existing
V2 schema and retains v3 canonical-output support representation. Outputs remain
an array with existing names/kinds, raw eligible strategic_parent_id, text/numeric
assertion rules, one primary strategic design reference, exact constraints and all
other bounds. Canonical evidence_ids and parent_claim_ids are absent and forbidden
in the support-selection wire input. Instead each statement returns additional_evidence_support and
additional_parent_support: closed objects containing every source alias as a
required strictly boolean property.

experiments_support_selection_catalog maps sorted complete authorized sources to
e000/p000 aliases. Evidence comes from the same request-local evidence passed to
generation; parents come from parent_claims(request), including accepted
nonstrategic observations/recommendations. The existing 250-ID per-family cap is
retained. No source is filtered, ranked, inferred or silently truncated. Invalid or
ambiguous source scopes fail closed before provider I/O.

Canonical citation sets are the mandatory strategic parent UNION additional true
choices. False does not exclude the primary; an explicit primary/true overlap
names one set member. This is declared typed-set meaning, not deduplication of a
malformed canonical/model array. Integer/string booleans, missing/extra/unknown
aliases, legacy citation arrays and wrong versions are rejected. Duplicate JSON
keys still fail at the existing strict JSON parser. The decoder reuses the V2
scalar mapper after converting validated sets to internal arrays; the intermediate
arrays are not a resubmitted V2 generation payload. V3 canonical arrays retain the
original maximum of 32 per family, including primary overlap; oversized selections
fail without truncation.

No CMO numeric-context citation binding is introduced. A numerical statement still
needs its actual selected sources to support it. A request-wide allowed assertion
alone does not cite its source; structured parent numeric_context never gains
assertion authority. The decoder preserves all prose, experiments, exact constraints
and assumptions/limitations. Original canonical schema, Pydantic, duplicate/identity,
strategic, numeric/word-quantity, constraint, confidence and Quality Gate checks
remain authoritative after decoding. This is a versioned provider representation,
not equivalence with V2 raw-response acceptance or a relaxation of canonical rules.

Version 4 gives `evidence_basis` a closed epistemic provenance note in Russian or
English: the explicitly selected accepted strategic hypothesis guides the
experiment and does not establish its effectiveness. It adds two disjoint nested
statement branches distinguished by `output_name`: `evidence_basis` and the other
fifteen outputs. Only the former text is constrained to that note. All other text,
kinds, confidence, explicit citation selections, mandatory strategic parent, field
and array bounds remain unchanged. Notes do not claim that a demonstration exists,
proves a recurring service format, or establishes customer outcomes. They cannot
promote a hypothesis into efficacy proof. There is no implicit demo citation.

The source statement is still canonical v1 after decoding. Existing accepted
artifacts/history are read as before; new wire responses must use the current version. Duplicate or
missing outputs remain canonical coverage failures. Unknown statement names, source
definition collisions, text bounds and unexpected schema shapes fail closed before
provider I/O. A changed wire version never authorizes repeating a completed durable
operation. Historical diagnostic failures remain unchanged.

Version 5 adds a third disjoint statement branch for `guardrails`. Its qualitative
text is a closed RU/EN publication policy: public copy must match confirmed owner
product descriptions and must not promise unconfirmed features or outcomes. This
avoids repeatedly generating free-form policy wording that can resemble delivery
claims. It is an intentionally narrower generation subset, not equivalence with
every valid free-form guardrail. The original alternative for complete supplied
numerical assertions remains intact; its enum must contain recognized quantities,
and original canonical validation still requires the actual selected source for
the complete statement. It cannot become an arbitrary qualitative escape.

`evidence_basis` keeps its v4 notes. The other fourteen output contracts remain
unchanged, including experiment-specific stop/scale decisions and learning records.
Nested designs, failure conditions, input requirements, citations, mandatory
strategic parent, field/array bounds and canonical v1 history are unchanged. An
unprovided outcome or unsupported numerical target does not become an accepted
guardrail. No source is selected implicitly by either kind of policy note.

## Bounded generation overhead

Before dispatch, expected output count times total source aliases must not exceed
2048 required boolean flags. This bounds representation overhead, not precise token
usage or provider completion. Full scope is retained or the request fails closed.
One output with 250 evidence plus 250 parents fits this preflight; 16 outputs with
500 total aliases does not. Exactly 2048 is allowed. Complete enum/string/schema
budgets are checked after construction; obsolete authority definitions are not
pruned to hide their budget. Only counts are added to schema telemetry. For a partial request, the unchanged
root outputs array can still admit extra wire outputs until canonical coverage
rejects them. The limit therefore describes expected required flags, not the
maximum size of every schema-valid response.

The existing output/token budgets and retry owners remain unchanged. The complete
EXPERIMENTS profile stays 16000 tokens, and boolean output can reduce room available
for prose/reasoning. Offline checks do not establish live model compliance, semantic
quality or two clean final workflows. Rollout and paid calls are outside this change.

## Offline verification

Tests retain the V2 duplicate baseline and check its valid-set V3 counterpart through
original gates and v1 serialization. They cover primary overlap, nonstrategic extra
lineage, actual-cited numeric/word support, context-only denial, canonical overflow,
all flags/constructors/wiring, immutable source/wire schemas, full 250-family scopes,
2048 preflight boundaries, complete schema budgets, strict typed negative cases,
duplicate JSON parsing, mocked real HTTP adaptation with one attempt and no inner
retry, provider mutation, and unchanged V2 input/instruction bytes. No operational
reports, runbook pins or historical data are rewritten.
