# Common module statement support

The production `POSITIONING` failure after PR #103 reached `support_missing`.
That stage proves at least one parsed statement had both `evidence_ids=[]` and
`parent_claim_ids=[]`; the historical output name is unknown. The provider
completed its response, but its strict schema allowed a state that
`BaseExecutor.build_result` always rejects.

`OutputStatement` now owns the support floor for all six executor families and
all four POSITIONING seed shapes. A Pydantic model validator rejects empty/empty.
Because model validators do not emit cross-field JSON Schema constraints, one
inherited schema hook emits two complete strict object alternatives in `anyOf`:
one sets `evidence_ids.minItems=1`, the other sets `parent_claim_ids.minItems=1`.
Each branch copies the derived statement's fields, required keys, bounds, output
names and kinds. Local-only, parent-only and both-nonempty remain valid. There is
no public support object, new field, payload version, registry or migration.

The hook is deterministic and independent of request/module/user content. It
does not select identities: supplied-ID validation and stronger executor rules
remain authoritative. Product claims still require local product truth/proof;
parent-only support cannot meet that rule. Missing seed kind restrictions,
competitor external evidence, CREATOR lineage and strategic parents are retained.
The runtime `SUPPORT_MISSING` guard remains for internal validation bypasses.
Provider violations now fail during parsing at `schema_invalid`, without repair
or retry. Budgets remain 16000 for full POSITIONING and 4000 for generic calls.

`test_statement_support_contract.py` captures schemas from actual executor calls
and checks every emitted statement definition with a JSON Schema validator and
its Pydantic parser against all four support shapes. The synthetic HTTP provider
first proposes empty support for absent seeds and checks the actual schema before
selecting real supplied support. Worker and PostgreSQL regressions verify all 16
claims are accepted, the artifact is persisted and VIRTUAL_CMO becomes pending.
No live provider call or historical provider response is used in these tests.
