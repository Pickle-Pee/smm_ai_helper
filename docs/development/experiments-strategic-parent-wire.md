# EXPERIMENTS strategic parent provider contract

The canonical contract remains `experiments.payload.v1`; no persisted schema or
migration changes. Existing artifacts deserialize unchanged. Every accepted
canonical statement already needed a material HYPOTHESIS from VIRTUAL_CMO or
POSITIONING. `support_requirement_for` now uses `PARENT_REQUIRED` to express its
nonempty parent floor before model execution. This is an alignment with the
existing semantic acceptance rule, not an equivalence claim about the former
ANY-support JSON Schema. Empty parents now fail at `schema_invalid`; known
nonstrategic-only citations still reach `output_missing_strategic_parent`.

`EXPERIMENTS_STRATEGIC_PARENT_WIRE_ENABLED` is a typed, default-off switch,
independent of `EXPERIMENTS_SCHEMA_PROJECTION_ENABLED`. With the wire enabled,
the model receives `experiments.wire.v2`. The authoritative existing
`strategic_parents(request)` selects eligible IDs. Each statement must explicitly
select `strategic_parent_id` from that exact enum. Design
`related_strategic_claim_ids` uses the same enum. Statement kinds are HYPOTHESIS
or RECOMMENDATION, matching the unchanged local guard. Additional
`parent_claim_ids` retain the complete original parent allowlist so accepted
observations and recommendations can still contribute lineage.

One parent slot is reserved for the explicit selection: additional arrays allow
0..31 references, the decoded canonical array allows 1..32. If the selected ID is
already present exactly once in the additional array, both explicit
representations name one canonical citation and the array stays unchanged.
Otherwise the selected ID is prepended. Duplicates within either support array
are rejected; neither the decoder nor the first statement's design/constraint
union repairs malformed duplicates. No citation is inferred from statement text.
The version and selected scalar are removed before original schema validation,
Pydantic parsing, strategic intersection/subset checks, duplicate guards, exact
numerical grounding, constraint equality, normalization and Quality Gates.

The wire builder first proves removal of redundant and single support ORs; proof
refusal stops before provider I/O. It retains closed objects, required fields,
strict bounds and complete-schema provider enum/string budgets. With only the
existing projection flag enabled, the same proven OR simplification precedes
annotation removal. With both flags disabled the parent-required schema remains
unprojected. Provider schema mutations cannot change the original validator.
Telemetry identifies the input schema contract version and wire switch, counts
annotations actually removed, and reports a projection only when the provider
schema differs from its input schema. In wire mode `validation_schema_*` refers
to the complete wire validator supplied to the projection hook; canonical v1 is
still independently validated by BaseExecutor after decoding.

Historical diagnostics keep incident byte/hash pins unchanged. Captures use the
current parent-required builders, explicitly labelled
`current_parent_required_builders_incident_model`; they must not be described as
an exact reconstruction of the old schema. The older one-call runbook retains
historical fingerprints and stops if current builders differ. New live wire
acceptance requires a separately reviewed request and bounded provider call;
o offline test makes a model-quality or rollout claim.

Offline regression coverage: `test_experiments_support_wire.py`,
`test_experiments_provider_projection.py`, `test_experiments_result_rules.py`,
`test_experiments_diagnostics.py`, and `test_strategy_intelligence.py`.

A subsequent one-POST diagnostic with the same wire request completed but was
rejected specifically by `numerical_support_required`. The unchanged guard rejects
new numeric prose even when related numbers occur in context. The instruction now
explicitly requires qualitative newly composed statements/designs, forbids digits
and numbered lists, and preserves supplied numeric constraints in their verbatim
constraint array. Entire supported numeric assertions remain allowed verbatim;
there is no local acceptance relaxation. Current composed instructions are 53477
UTF-8 bytes; the historical incident pin remains 53096 and diagnostics report the
381-byte difference instead of claiming an exact replay.
