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

The current version is experiments.support_selection.v7. It is built on the existing
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
missing outputs remain rejected. Unknown statement names, source
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

Version 6 makes the uniquely named `evidence_basis` the first canonical output,
regardless of model array order. The executor attaches nested design data and
checks its selected witnesses on that first claim. Only the statement moves:
content, selected source flags and the relative order of all other outputs are
preserved. No other output's citations are borrowed or unioned into its evidence.
A full request requires the basis exactly once. Partial requests containing it
also move it first; partial requests without it retain their original first-output
ownership contract. Duplicate/missing output rejection and canonical bounds remain.
Historical accepted payloads are not reordered or rewritten.

The same v6 generation schema applies the existing small RU/EN two-form filter
to free qualitative statement/design text, including minimum-input items. It
does not touch complete source/numerical enums. The authorized assertion catalogs
now recognize the existing canonical word-quantity detector as well as digits,
preserving exact supplied `two/двух` quotations that previously fit qualitative
generation. Every numerical statement/design still needs its actual selected
source and complete exact assertion; an allowed enum is not an implicit citation.
Other quantities and unlisted languages remain subject to canonical validation.
The wire version changes the request fingerprint, never the durable operation ID
or the prohibition on repeating a completed/unknown provider operation.

Version 7 gives `control` and `treatment` disjoint operator-plan branches. Closed
RU/EN notes require preparing new messages from confirmed owner facts and the
explicitly selected strategic hypothesis, then obtaining owner approval before
testing. They do not claim current messages, landing pages, service properties or
completed approval. Complete supplied numerical assertions retain their original
alternative and actual selected-source checks; numerical text cannot manufacture
authority for an unconfirmed asset or delivery claim.

Nested `intervention` chooses a complete recipe within its existing 300-character
bound: prepare/approve and compare new messages, or prepare/approve and research
them in qualitative audience interviews. Both recipes have RU/EN variants. The
separate selected design hypothesis supplies the actual experimental focus;
metrics, expected signals, falsifiers, sizing/stops, input requirements and all
twelve other output text contracts retain their prior authority and bounds.
Exact supplied numerical intervention assertions remain available through the
original source enum. Free-form fragments or presumed existing assets do not.

This is a deliberately bounded communication/message-validation generation
subset, not an equivalent replacement for every possible EXPERIMENTS plan. It
preserves complete useful operator steps instead of truncated ad-copy fragments.
Other valid free-form control, treatment or intervention prose can reject with
this opt-in wire. Canonical v1 history, source selection, first-basis design
ownership and durable operation IDs remain unchanged. Earlier accepted artifacts
and failed diagnostic responses are never rewritten by a new wire version.

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
