# CMO provider prose and numeric-pair contract

Two production CMO responses completed but were rejected locally: one placed
digits in strategic items; another selected a numeric_context source with no
eligible quotation unit. These are distinct failures. No raw business text is
required to classify them, and HTTP completion is not business acceptance.

## Provider restrictions and authority

VirtualCMOExecutor.provider_schema_for retains the existing proven support-OR
collapse, then applies a request-owned provider contract. It obtains evidence
with exactly first_party_evidence(request, scoped_facts(request)) and parents
with parent_claims(request), matching execution. The existing numeric_quote_catalog
is the sole selector of eligible support_id/exact_quote pairs. Its existing caps
remain 64 complete entries and 16384 serialized UTF-8 bytes.

CMO statement text and each strategy item receive the portable ^[^0-9]*$ pattern.
The local numerical guard already forbids all Unicode decimal digits in these
fields, even when supplied. Thus this provider restriction does not exclude
locally accepted prose. It is not a claim that the structural schema previously
contained the rule, or that an ASCII pattern proves absence of every Unicode
digit. The unchanged Unicode-aware local guard remains authoritative.

When pairs exist, the shared provider NumericContext definition uses full closed
object anyOf branches grouped by support_id. Each branch has that literal source
identity and an enum of its own complete catalog quotations. An ID from one
source cannot be paired with another source's quotation merely because both are
individually in scope. Original reference/string bounds and required/closed-object
rules remain. With no eligible pairs, every statement numeric_context array has
provider maxItems=0; no empty enum or invented quotation is introduced.

This is intentionally a bounded provider subset of the canonical structural
contract. Catalog caps can omit otherwise locally eligible complete pairs. No
truncated quote, fuzzy match or replacement source is substituted. Grouping the
bounded union may still affect provider grammar performance; deterministic tests
do not establish live completion rates.

## No catalog-mode or binding activation

Using the catalog as a private schema selector does not add catalog advice to
model input, change instructions or enable VIRTUAL_CMO_NUMERIC_QUOTE_CATALOG_ENABLED.
That flag remains default false. Its existing append-only citation binding is
not invoked by this provider projection. No model response is repaired and no
missing citation is filled in. An allowed exact pair still fails locally if its
source is not cited in the appropriate evidence/parent array.

The original NumericContext Pydantic/schema contract, support allowlists/floors,
strategy kinds/coverage, exact full quotation checks, source attribution,
confidence, Quality Gates and atomic graph persistence remain authoritative.
The original schema is copied, never mutated. Unknown shapes, references or
bounds and complete-schema provider-budget overflow stop before model I/O,
without fallback. Accepted payloads remain virtual_cmo.payload.v1; no DTO,
registry or database migration changes, and old artifacts are not rewritten.

## Verification

Before the fix, three provider-schema regressions failed because digit text,
digit items and a numeric context pointing at a source without an eligible quote
were all structurally permitted. New tests cover complete same-source pairs,
cross-source mismatches, fragments, changed/unknown identities, empty catalogs,
shared-source quote grouping, full bounds, immutable canonical schemas,
idempotent prose patterns, existing parent/local floors, catalog and total schema
budgets, and Unicode failures at the unchanged server guard. Executor tests check
original gates and verify that advice/binding remain off and an uncited exact
source is not repaired. Adjacent numeric-grounding/binding/diagnostic suites
remain applicable. Offline checks do not replace two clean final Telegram runs,
real strategy-quality assessment or separately authorized live acceptance.
