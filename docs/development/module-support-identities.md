# Request-scoped module support identities

The production POSITIONING failure at `parent_reference_invalid` proves that at
least one returned parent ID was outside the accepted server-owned parent set.
The exact generated ID is unknown: raw model output is intentionally not logged.
For the reported strategy shape there are no explicit research/competitor inputs,
so POSITIONING has local first-party evidence but no research predecessors. The
static support OR allowed an arbitrary parent reference despite that empty set.
The same gap existed for arbitrary local evidence references.

All six executable modules use `BaseExecutor.generate`. Its selected Pydantic
output type continues to own fields, bounds, kinds and the static support floor.
`support_response_schema` scopes that schema using only supplied LocalEvidence
record IDs and accepted `parent_claims(request)` IDs. The latter excludes failed,
blocked and out-of-scope upstream claims. The graph's accepted ancestor closure
determines which upstream results are available; this change does not alter it.

Available identity enums are sorted and defined once in `AllowedEvidenceId` and
`AllowedParentClaimId`. Array items reference these definitions, including every
inherited statement OR branch. Sharing avoids duplicating enum values in the
POSITIONING seed variants. Unavailable arrays retain a valid bounded string item
schema with `maxItems=0`; their support-floor branch is removed. There are no
empty enums, unsupported composition keywords, or root-level ORs.

| Local evidence | Accepted parents | Valid support |
| --- | --- | --- |
| present | absent | One or more allowed local IDs, empty parents |
| absent | present | Empty local IDs, one or more allowed parent IDs |
| present | present | Local-only, parent-only, or both; all IDs allowed |
| absent | absent | BLOCKED / MISSING_BLOCKING_INPUT before model call |

The schema is checked by the fixed `Draft202012Validator` before provider use.
The response is bounded JSON text, decoded with duplicate-key/nonfinite-value
rejection, then validated against the exact emitted schema, then parsed through
the selected `output_type.model_validate_json`. Schema violations become the
bounded `SCHEMA_INVALID` stage without exposing validation errors or payloads.
`build_result` retains evidence/parent reference checks and SUPPORT_MISSING for
internal bypass. No generated support is repaired, removed, inferred or retried.
Existing executor-specific product truth, hypothesis and lineage semantics remain
additional requirements, as do the 16000/4000 budgets and single provider attempt.

## Bounds and empty-support reachability

Each identity family permits at most **250 distinct IDs**, each 1–128 characters.
The complete emitted schema is also checked for at most 1000 enum values and
120000 characters in property/definition names and enum/const strings. A family
of 250 values avoids the provider's additional string-size restriction for enums
with more than 250 values. These limits follow the
[Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).
Oversized internal requests fail with ModuleExecutionContractError before calling
the model; allowlists are never truncated. Statement support arrays remain bounded
to 32 items. These are generation bounds, not changes to persisted/public types.

Current normal entrypoints cannot reach empty/empty generation: POSITIONING
requires product, target and product_truth; CREATOR requires product and format;
VIRTUAL_CMO requires business_goal and product context; MARKET_ANALYSIS requires
product/category plus research or parents; COMPETITOR_ANALYSIS requires observable
page evidence; EXPERIMENTS requires accepted strategic hypothesis parents.
EXPERIMENTS can legitimately have no locals. The common empty/empty guard covers
internal bypass and future executors without inventing support.

## Verification scope

The schema matrix tests cover valid, invented and unavailable IDs and empty/empty.
Captured schemas cover every selected POSITIONING seed type and all other modules.
Downstream tests constrain VIRTUAL_CMO to accepted POSITIONING claims and
EXPERIMENTS to available VIRTUAL_CMO claims. Production transport tests first
propose invented evidence/parent IDs; strict generation excludes them. Separately,
a provider ignoring the schema is rejected before result construction.

The no-research strategy regression crosses the production HTTP adapter and graph
worker: POSITIONING produces PASS_WITH_LIMITATIONS and 16 accepted claims; the
PostgreSQL counterpart persists its artifact and schedules VIRTUAL_CMO PENDING,
with exactly one provider call. Registry 1.3.0, registry JSON, public API,
compiled plans and migrations are unchanged; Alembic head is 20261006_0011.
