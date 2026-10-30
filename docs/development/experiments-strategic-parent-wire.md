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

That guidance probe completed but the original constraint-equality guard rejected
`experiment_constraints_mismatch`. The wire now expresses the same authoritative
constraint set: exact cardinality and an enum of the supplied verbatim values,
or an empty array when no constraints exist. It uses the same evidence selector
as local validation (scoped constraints, time_resource_constraint, budget and
duration), without inferring constraints from unrelated product descriptions.
The unchanged local uniqueness/set-equality guard still rejects duplicates and
omissions; no decoder adds, removes or rewrites constraints. Unrepresentable
input stops before provider I/O. These wire restrictions do not change the
canonical accepted set or stored v1 payload.


## Qualitative design generation and exact numeric assertions

With the strategic wire enabled, the five free-text ExperimentDesign fields and
string items in `minimum_required_inputs` use a portable `^[^0-9]*$` pattern.
When authoritative `assertion_support` from eligible strategic parents supplies
complete numerical assertions of 1..300 characters, the field instead accepts a
nested `anyOf`: qualitative text or a direct local reference to the shared
`AllowedExperimentNumericAssertion` definition. That single string enum contains
the exact full assertions with the same original 1..300 character bounds. All
six fields reuse it instead of repeating its values. Definition-name collisions
fail closed. This encoding accepts the same values as six inline enums. No numeric assertions means
pattern only, with no extra OR. This provider restriction intentionally allows
complete supplied assertions, rather than every substring accepted by the
canonical guard. Longer source assertions cannot fit these design fields and do
not become enum entries. New words, fragments and calculated replacements are
not added to the enum. Structured `numeric_context` quotes are never assertion
support. The canonical persisted validation schema remains unchanged; provider statement generation is constrained separately below.

The portable pattern excludes ASCII digits; it is not a proof about all Unicode
decimal digits. The existing Unicode-aware numerical guard remains authoritative.
The provider allowlist spans eligible request parents; the unchanged original
per-design guard still requires a numerical field to be supported by its actual
`related_strategic_claim_ids`. Thus selecting a full assertion from one parent
while citing another still fails locally. Exact time/resource constraint enums,
reference bounds, selected-parent decoding and stored v1 payloads are unchanged.
With the wire disabled, the canonical design schema is unchanged. Complete-schema
provider enum/string limits are checked after these additions, and refusal never
falls back to a permissive schema. This change performs no output rewriting.


## Canonical statement generation

Canonical `ExperimentStatement.text` now follows the same qualitative-or-exact
provider rule, with its original 1..4000 character bounds. A single shared
`AllowedExperimentStatementNumericAssertion` string enum contains complete
bounded numerical support values. The text field uses a direct local reference
alongside the qualitative ASCII pattern. Without numerical support it uses the
pattern alone. Name collisions refuse generation. The existing design enum and
its 1..300 bounds remain separate.

Statement assertion scope exactly matches the available channels of the existing
`intelligence_common.supported_text`: local evidence string values are retained;
other local values use `json.dumps(plain(value), ensure_ascii=False)`; all accepted
parent claims provide `assertion_support(value)`, including accepted nonstrategic
parents. This differs deliberately from design assertions, which only use
eligible strategic parents. Structured parent `numeric_context` remains excluded.
The executor does not invent a source quote or change the model input, decoder,
statement text, canonical payload schema, or persisted payloads.

The enum is a request-wide generation aid. Existing numerical semantics still
require the output to be supported by the evidence/parents actually cited on that
statement. A complete assertion selected from an uncited available source remains
invalid locally. The provider enum allows only full supplied assertions, although
the unchanged canonical guard accepts literal substrings as well. New words,
numerical paraphrases and calculations do not become enum entries. ASCII pattern
portability and the authoritative Unicode-aware server guard remain as described
above. Corpus enum/string budgets are checked once after both shared assertion
definitions, exact constraints and all request-specific references are installed.
