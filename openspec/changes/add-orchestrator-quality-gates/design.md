# Design: Exact deterministic orchestrator quality gates

## Context

The existing `app/marketing_orchestrator/` package is a pure `PLANNING_ONLY` planner. Registry `1.0.0` supplies read-only metadata but no execution bindings or invocation-specific output schemas. Existing agents return heterogeneous dictionaries. This foundation therefore begins only at an explicitly normalized caller boundary.

## Goals / Non-Goals

**Goals:** exact immutable contracts, total validation/error behavior, derived gate/decision/eligibility states, conservative lineage propagation, typed contradictions, and independently testable isolation.

**Non-Goals:** adapters, execution, semantic truth/causality/strategy checks, LLM/QC, persistence, workflows, revised plans, APIs/Telegram, or prose synthesis.

## Runtime ownership and dependencies

The only planned runtime package is `app/marketing_orchestrator/quality_gates/`:

- `contracts.py`: all enums and frozen/slotted contracts;
- `errors.py`: `QualityGateContractError`;
- `evaluator.py`: ordered validation and final gate derivation;
- `propagation.py`: lineage, provenance, confidence and limitation propagation;
- `contradictions.py`: comparison and precedence;
- `decisions.py`: gate-compatible replan/stop decisions;
- `__init__.py`: only supported internal contract, evaluator and decision exports.

It may import public `ModuleId`, `ModuleResultStatus`, `ModuleRegistry`, Registry lookup errors and immutable descriptor types. It must not import agents, presenters, routers, `QCService`, OpenAI clients, persistence/context services, Jobs, Redis, workers or workflow execution. Existing planner/validator modules do not import this package and remain unchanged. This direction prevents circular imports. Nothing is exported through a public API.

## Canonical finite vocabulary

Every value is an exact enum instance; raw strings and duplicate synonyms are rejected.

- `ClaimType`: `FACT`, `OBSERVATION`, `INFERENCE`, `HYPOTHESIS`, `ASSUMPTION`, `FORECAST`, `RECOMMENDATION`.
- `Confidence`: `UNKNOWN`, `LOW`, `MEDIUM`, `HIGH`; total conservative order `UNKNOWN < LOW < MEDIUM < HIGH`.
- existing `ModuleResultStatus`: `PASS`, `PASS_WITH_LIMITATIONS`, `FAIL`, `BLOCKED`.
- separate derived `GateOutcome`: `PASS`, `PASS_WITH_LIMITATIONS`, `FAIL`, `BLOCKED`.
- `StructuralValidity`: `VALID` (invalid contracts raise and produce no value).
- `ExecutionReadiness`: `PLANNING_ONLY` (derived only).
- `SynthesisEligibility`: `ELIGIBLE`, `INELIGIBLE` (derived only).
- `EvidenceSufficiency`: `SUFFICIENT`, `LIMITED`, `INSUFFICIENT`, `NOT_ASSESSED`.
- `EvidenceSourceClass`: `FIRST_PARTY`, `EXTERNAL_PRIMARY`, `EXTERNAL_SECONDARY`, `GENERIC_BENCHMARK`, `SYNTHETIC`, `UNKNOWN`.
- `ClaimLineageType`: `ORIGINAL`, `REPEATS`, `REFORMULATES`, `DERIVES`.
- `Materiality`: `MATERIAL`, `NON_MATERIAL`.
- `AuthorityStatus`: `WITHIN_SCOPE`, `REQUIRES_REVIEW`, `OUT_OF_SCOPE`.
- `LimitationReason`: `MISSING_PREFERRED_INPUT`, `INCOMPLETE_COVERAGE`, `INSUFFICIENT_EVIDENCE`, `STALE_EVIDENCE`, `TOOL_LIMIT`, `CAPABILITY_LIMIT`, `ASSUMPTION_DEPENDENCY`, `UNRESOLVED_CONTRADICTION`, `OUT_OF_SCOPE`.
- `FailureReason`: `MODULE_DECLARED_FAILURE`, `NO_USABLE_CLAIMS`, `INSUFFICIENT_EVIDENCE`, `DECLARED_OUTPUT_MISSING`, `AUTHORITY_VIOLATION`.
- `BlockingReason`: `MISSING_BLOCKING_INPUT`, `MISSING_CAPABILITY`, `TOOL_UNAVAILABLE`, `DEPENDENCY_BLOCKED`, `AUTHORIZATION_REQUIRED`.
- `ContradictionState`: `UNRESOLVED`, `PRIORITIZED`, `INCOMPARABLE`.
- `ContradictionPrecedenceReason`: `FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK`.
- `FreshnessComparison`: `NEWER`, `OLDER`, `SAME`, `UNKNOWN`.
- `ExclusionReason`: `RESULT_FAILED`, `RESULT_BLOCKED`, `UNRESOLVED_CONTRADICTION`, `CONTRADICTION_PRECEDENCE`.
- `ExclusionSubjectType`: `RESULT`, `CLAIM`.
- `ReplanningDecision`: `CONTINUE_CURRENT_PLAN`, `REPLAN_REQUIRED`, `STOP`, `BLOCKED`.
- `ReplanReason`: `MATERIAL_FINDING`, `DEPENDENCY_INVALIDATED`, `REVERSIBLE_TEST_HIGHER_VALUE`.
- `StopReason`: `SCOPE_COMPLETE`, `SUFFICIENT_EVIDENCE`, `DIMINISHING_VALUE`, `TOOL_LIMIT_REACHED`, `CAPABILITY_LIMIT_REACHED`, `RESULT_FAILED`.

## Exact scalar, container and ID domain

Caller scalars are exact built-in `None`, `bool`, `int`, finite `float`, or `str`; bool is never accepted where int is required. Prose is exact non-empty `str`. Ordered fields accept exact `list` or `tuple`, are validated item-first and copied to tuple. Semantic sets accept exact `list`, `tuple`, `set` or `frozenset`, reject duplicates before freezing, and emit enum/ID lexical order. Exact dictionaries are allowed only for fields explicitly declared as mappings, require exact string keys, and become copied internal mapping proxies. No contract below currently exposes a caller mapping field. Mapping proxies are output-only and rejected if resubmitted.

Entity IDs are exact ASCII built-in strings, are not trimmed/case-folded/normalized, have maximum length 67, and match:

```regex
^(bat|res|clm|evd|asm|lim|ctr|exc)_[a-z0-9][a-z0-9_-]{0,62}$
```

Field prefixes are mandatory: batch `bat_`, result `res_`, claim `clm_`, evidence `evd_`, assumption `asm_`, limitation `lim_`, contradiction `ctr_`, and exclusion `exc_`. These are distinct typed-string contracts. There is no decision or manifest ID. Wrong prefixes and duplicate IDs are errors even when records are equal. `BatchFingerprint` is an exact built-in string matching `^[0-9a-f]{64}$` and is always derived.

Comparison keys (`object_key`, `segment_key`, `period_key`, `metric_definition_key`) are exact non-empty ASCII strings matching `^[a-z0-9][a-z0-9_.:-]{0,127}$`; they are complete caller-supplied typed scope metadata and are never derived from claim, evidence, module-output or Registry prose. The existing normative `period_key` and `metric_definition_key` names are retained without synonyms.

## Planned dataclasses

All are frozen/slotted. “Empty forbidden” means empty string/container is a contract error.

| Contract.field | Exact type | Required/default | Empty/order | Supply |
| --- | --- | --- | --- | --- |
| `EvidenceRecord.evidence_id` | prefixed `str` | required | unique batch-wide | caller |
| `.source_class` | `EvidenceSourceClass` | required | n/a | caller |
| `.provenance` | exact non-empty `str` | required | no normalization | caller |
| `.observed_at` | exact aware `datetime | None` | default `None` | normalized UTC | caller |
| `AssumptionRecord.assumption_id` | prefixed `str` | required | unique batch-wide | caller |
| `.description` | exact non-empty `str` | required | prose only | caller |
| `.materiality` | `Materiality` | required | n/a | caller |
| `LimitationRecord.limitation_id` | `LimitationId` | required | unique batch-wide | caller only |
| `.reason/.materiality` | `LimitationReason`, `Materiality` | required | exact enums | caller only |
| `.related_result_ids` | tuple of `ResultId` | default `()` | unique lexical; batch-resolved | caller only |
| `.related_claim_ids` | tuple of `ClaimId` | default `()` | unique lexical; batch-resolved; caller limitation must reference a result or claim | caller only |
| `.related_contradiction_ids` | tuple of `ContradictionId` | default `()` | unique lexical; batch-resolved | caller only |
| `.description` | exact non-empty `str | None` | default `None` | no normalization | caller only |
| `NormalizedClaim.claim_id` | prefixed `str` | required | unique batch-wide | caller |
| `.declared_output_name` | exact non-empty `str` | required | exact Registry membership | caller |
| `.claim_type` | `ClaimType` | required | exact enum | caller |
| `.confidence` | `Confidence` | required | canonical order | caller |
| `.authority_status` | `AuthorityStatus` | required | exact enum | caller |
| `.value` | exact scalar | required | string may be empty only as a scalar value | caller |
| `.lineage_type` | `ClaimLineageType` | required | n/a | caller |
| `.parent_claim_ids` | tuple of claim IDs | default `()` | lexical; rules below | caller |
| `.evidence_ids` | tuple of `EvidenceId` | default `()` | unique lexical, result-local resolved | caller |
| `.assumption_ids` | tuple of `AssumptionId` | default `()` | unique lexical, result-local resolved | caller |
| `.limitation_ids` | tuple of `LimitationId` | default `()` | unique lexical, result-local resolved | caller |
| `NormalizedModuleResult.result_id` | prefixed `str` | required | unique batch-wide | caller |
| `.module_id` | `ModuleId` | required | exact Registry enum | caller |
| `.module_status` | `ModuleResultStatus` | required | exact enum | caller |
| `.claims` | tuple of `NormalizedClaim` | default `()` | claim-ID lexical, copied/frozen | caller |
| `.evidence` | tuple of `EvidenceRecord` | default `()` | evidence-ID lexical, copied/frozen | caller |
| `.assumptions` | tuple of `AssumptionRecord` | default `()` | assumption-ID lexical, copied/frozen | caller |
| `.limitations` | tuple of `LimitationRecord` | default `()` | limitation-ID lexical, copied/frozen | caller |
| `.failure_reasons` | frozenset of `FailureReason` | default empty | frozen; output enum-value order | caller |
| `.blocking_reasons` | frozenset of `BlockingReason` | default empty | frozen; output enum-value order | caller |
| `.evidence_sufficiency` | `EvidenceSufficiency` | required | n/a | caller |
| `.handoff_module_ids` | semantic set of `ModuleId` | default empty | ModuleId value order | caller |
| `ContradictionSide.claim_id` | `ClaimId` | required | batch-resolved | caller |
| `.evidence_id` | `EvidenceId | None` | default `None` | when selected, belongs to this side's claim | caller |
| `.object_key` | comparison-key `str` | required | complete exact value | caller |
| `.segment_key` | comparison-key `str` | required | complete exact value | caller |
| `.period_key` | comparison-key `str` | required | complete exact value | caller |
| `.metric_definition_key` | comparison-key `str` | required | complete exact value | caller |
| `ContradictionInput.contradiction_id` | prefixed `str` | required | unique batch-wide | caller |
| `.left` | exact `ContradictionSide` | required | copied/frozen; caller position preserved | caller |
| `.right` | exact `ContradictionSide` | required | copied/frozen; distinct claim ID; caller position preserved | caller |
| `EvaluationBatch.batch_id` | batch ID | required | stable batch association | caller |
| `EvaluationBatch.results` | tuple of `NormalizedModuleResult` | required | non-empty, result-ID order, copied/frozen | caller |
| `.contradictions` | tuple of `ContradictionInput` | default `()` | contradiction-ID order, copied/frozen | caller |
| `.evaluation_at` | exact aware `datetime | None` | default `None` | normalized UTC; metadata only | caller |
| `.batch_fingerprint` | exact lowercase 64-hex string | no caller value | canonical batch hash | derived |

No caller supplies structural validity, `GateOutcome`, execution readiness, synthesis eligibility, contradiction state/precedence, exclusion records, manifest content or batch fingerprint.

### Complete derived and cross-stage contracts

Every tuple below is deeply immutable, duplicate-free, and lexically ordered by typed ID or enum `.value`; `default ()` means empty is legal except where a coherence rule says otherwise. All references resolve within the named batch or its deterministic derived records.

| Contract | Exact fields |
| --- | --- |
| `GateDecision` | `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `result_id: ResultId`; `module_id: ModuleId`; `module_status: ModuleResultStatus`; `structural_validity: StructuralValidity`; `gate_outcome: GateOutcome`; `evidence_sufficiency: EvidenceSufficiency`; `accepted_claim_ids: tuple[ClaimId,...]=()`; `excluded_claim_ids: tuple[ClaimId,...]=()`; `assumption_ids: tuple[AssumptionId,...]=()`; `evidence_ids: tuple[EvidenceId,...]=()`; `limitation_ids: tuple[LimitationId,...]=()`; `contradiction_ids: tuple[ContradictionId,...]=()`; `failure_reasons: tuple[FailureReason,...]=()`; `blocking_reasons: tuple[BlockingReason,...]=()`; `authority_status: AuthorityStatus`; `synthesis_eligibility: SynthesisEligibility`; `execution_readiness: ExecutionReadiness` |
| `ContradictionRecord` | `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `contradiction_id: ContradictionId`; `left: ContradictionSide`; `right: ContradictionSide`; `state: ContradictionState`; `preferred_claim_id: ClaimId|None=None`; `precedence_reason: ContradictionPrecedenceReason|None=None`; `preserved_claim_ids: tuple[ClaimId,ClaimId]`; `excluded_claim_ids: tuple[ClaimId,...]=()`; `derived_limitation_ids: tuple[LimitationId,...]=()` |
| `ExclusionRecord` | `exclusion_id: ExclusionId`; `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `subject_type: ExclusionSubjectType`; `result_id: ResultId|None=None`; `claim_id: ClaimId|None=None`; `reason: ExclusionReason`; `contradiction_id: ContradictionId|None=None`; `related_limitation_ids: tuple[LimitationId,...]=()` |
| `DecisionRequest` | `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `gate_decision: GateDecision`; `replan_reasons: frozenset[ReplanReason]=frozenset()`; `stop_reasons: frozenset[StopReason]=frozenset()`; `blocking_reasons: frozenset[BlockingReason]=frozenset()` |
| `DecisionResult` | `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `result_id: ResultId`; `gate_outcome: GateOutcome`; `decision: ReplanningDecision`; `replan_reasons: tuple[ReplanReason,...]=()`; `stop_reasons: tuple[StopReason,...]=()`; `blocking_reasons: tuple[BlockingReason,...]=()`; `execution_readiness: ExecutionReadiness` |
| `SynthesisEligibilityManifest` | `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `evaluated_result_ids: non-empty tuple[ResultId,...]`; `accepted_result_ids: tuple[ResultId,...]=()`; `accepted_claim_ids: tuple[ClaimId,...]=()`; `limitation_ids: tuple[LimitationId,...]=()`; `unresolved_contradiction_ids: tuple[ContradictionId,...]=()`; `exclusions: tuple[ExclusionRecord,...]=()`; `execution_readiness: ExecutionReadiness` |

All are frozen/slotted. `GateDecision` fields are copied or derived exactly as named: emitted validity is `VALID`; readiness is `PLANNING_ONLY`; accepted/excluded claims are disjoint; preserved evidence/assumption/limitation IDs are batch-resolved; `FAIL` has non-empty failure reasons and no accepted claims; `BLOCKED` has non-empty blockers and no accepted claims. Its authority is `WITHIN_SCOPE` if every accepted claim is within scope, otherwise `REQUIRES_REVIEW`; empty-claim failed/blocked results use `WITHIN_SCOPE`. `(batch_id, batch_fingerprint, result_id)` is the decision identity and no separate ID exists.

Every contradiction record copies batch association and the exact validated immutable `left` and `right` side values without duplicate flat fields. `preserved_claim_ids` is exactly both IDs, unique lexical. `INCOMPARABLE`/`UNRESOLVED` have no preferred claim/reason, exclude both claims, and contain one derived limitation per affected result, unique lexical. `PRIORITIZED` has exactly one preferred claim and `FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK`, excludes the one non-preferred claim, has no derived limitation, preserves both, and permits only the preferred claim into unqualified accepted IDs.

An exclusion has exactly one of result/claim ID. Failed result produces `RESULT_FAILED`; blocked result produces `RESULT_BLOCKED`; unresolved/incomparable claim produces `UNRESOLVED_CONTRADICTION` with contradiction and related limitation; prioritized non-preferred claim produces `CONTRADICTION_PRECEDENCE` with contradiction and no limitation. A claim may have multiple records for distinct contradiction preimages and is excluded if any exists; being preferred elsewhere does not override exclusion. These paths are exhaustive at ID-set level.

`DecisionRequest` accepts only exact built-in containers before freezing and exact enums; duplicates are rejected. Its batch ID and fingerprint must both equal the exact evaluator-produced gate decision. `DecisionResult` uses the matrix below for tuple emptiness and identity. One manifest is identified by `(batch_id, batch_fingerprint)`; every result occurs once in evaluated IDs, failed/blocked results are not accepted, unresolved claims are not accepted, exclusions are exhaustive, and the output contains no prose or public DTO.

### Derived limitations and complete evaluation output

`DerivedLimitationRecord` is a frozen/slotted output-only contract; callers cannot supply it.

| Field | Exact type and policy |
| --- | --- |
| `batch_id` | `BatchId`, required, copied from batch |
| `batch_fingerprint` | `BatchFingerprint`, required, copied |
| `limitation_id` | `LimitationId`, required, derived |
| `reason` | `LimitationReason`, required; contradiction path exactly `UNRESOLVED_CONTRADICTION` |
| `materiality` | `Materiality`, required; contradiction path exactly `MATERIAL` |
| `related_result_ids` | non-empty tuple of `ResultId`, unique lexical, same-batch resolved |
| `related_claim_ids` | non-empty tuple of `ClaimId`, unique lexical, same-batch resolved |
| `related_contradiction_ids` | non-empty tuple of `ContradictionId`, unique lexical, same-batch resolved |
| `description` | exact `None`, required; no prose |

Derived records use the canonical `lim_` algorithm, collision rules and lexical limitation-ID order. Gate decisions and manifests may reference caller and derived limitation IDs. Actual records are exposed by the aggregate below.

`BatchEvaluationResult` is frozen/slotted and contains: `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `gate_decisions: tuple[GateDecision,...]` exactly one per result ordered by result ID; `contradiction_records: tuple[ContradictionRecord,...]` exactly one per input ordered by contradiction ID; `derived_limitations: tuple[DerivedLimitationRecord,...]` unique by canonical preimage and ordered by limitation ID; `exclusions: tuple[ExclusionRecord,...]` unique by canonical preimage and ordered by exclusion ID; `synthesis_manifest: SynthesisEligibilityManifest`; and `execution_readiness: ExecutionReadiness` exactly `PLANNING_ONLY`. Every nested output carries identical batch ID/fingerprint. References resolve against caller records in the validated batch or derived records in this aggregate, never object identity.

### Exact GateDecision and manifest source sets

For each result, `evidence_ids` is every declared evidence ID; `assumption_ids` is every declared assumption ID; `limitation_ids` is the union of every declared caller limitation and every derived limitation whose related results contain it; and `contradiction_ids` is every contradiction whose left or right claim belongs to it. Each is unique lexical and may be empty.

`accepted_claim_ids` is exactly usable result claims with no claim exclusion. `excluded_claim_ids` is exactly result claims with at least one claim exclusion. They are unique lexical, disjoint, and for accepted results exhaustive over its claims. `failure_reasons` is caller validated reasons union exact derived reasons such as `NO_USABLE_CLAIMS`, unique enum-value order and non-empty only for `FAIL`. `blocking_reasons` is exactly caller validated blockers, unique enum-value order and non-empty only for `BLOCKED`.

Manifest `evaluated_result_ids` is all batch results once, lexical. `accepted_result_ids` is exactly final `PASS`/`PASS_WITH_LIMITATIONS`. `accepted_claim_ids` unions accepted-claim IDs from accepted results. `limitation_ids` unions limitation IDs from accepted results only. `unresolved_contradiction_ids` is exactly unresolved/incomparable records touching an accepted result. All are unique lexical.

Manifest exclusions contain exactly one result exclusion per failed/blocked result and claim contradiction exclusions only for claims belonging to accepted results; no separate claim exclusions are emitted inside failed/blocked results. Every evaluated result is accepted or has one result exclusion; every claim in an accepted result is accepted or has at least one claim exclusion; these ID sets are disjoint. Multiple claim exclusions are allowed for distinct contradiction preimages; identical preimages deduplicate.

## Namespace and reference rules

One immutable `EvaluationBatch` owns all namespaces. Batch, result, claim, evidence, assumption, limitation and contradiction IDs have independent namespaces; exclusion IDs are unique in derived outputs. Duplicate validation completes before reference resolution.

Evidence, assumption and caller-limitation references are result-local. Lineage and contradiction claim references may cross results only inside the same batch. Selected evidence resolves in its claim's owning result and must occur in that claim's `evidence_ids`.

### Canonical batch fingerprint and derived IDs

Fingerprinting builds the exact schema-tagged tree below and serializes it with RFC 8785 JSON Canonicalization Scheme, then SHA-256 over its RFC 8785 UTF-8 bytes. Valid Unicode scalar values are accepted; lone UTF-16 surrogates are rejected; NFC/NFD, case and whitespace normalization are forbidden. RFC 8785 escaping and object-key ordering are normative.

```json
{"schema":"quality-gates-batch-v1","batch_id":"<BatchId>","evaluation_at":"<datetime-or-null-node>","results":["<normalized-result-node>"],"contradictions":["<contradiction-input-node>"]}
```

Generic scalar nodes are exactly `{"t":"null"}`, `{"t":"bool","v":true}`, `{"t":"str","v":"text"}`, `{"t":"int","v":"-123"}`, or `{"t":"float64","v":"3ff0000000000000"}`. Bool is checked before int. Integer text is base ten with no plus/leading zeros and zero `"0"`. Finite floats use exact IEEE-754 binary64 big-endian 16-character lowercase hex; NaN/infinities are rejected and negative zero remains `8000000000000000`. Thus `1`, `1.0`, `0.0`, and `-0.0` differ. Enums are `{"t":"enum","n":"ExactEnumClassName","v":"EXACT_MEMBER_VALUE"}`. Datetimes are `{"t":"datetime","v":"YYYY-MM-DDTHH:MM:SS.ffffffZ"}` with exactly six digits. Sequences are `{"t":"array","v":[...]}`; mappings are `{"t":"object","v":{...}}` with exact accepted string keys. Exact list/tuple inputs are frozen before canonicalization.

| Canonical subtree | Exact caller source and order |
| --- | --- |
| root `batch_id` | canonical BatchId unchanged |
| root `evaluation_at` | datetime node or null node |
| root `results` | every `NormalizedModuleResult`, result-ID lexical |
| result node | all fields in the input table: IDs/enums/scalar through tagged nodes; claims/evidence/assumptions/limitations in respective ID order; failure/blocking enum sets by enum value; handoffs by `ModuleId.value` |
| claim node | every caller field: IDs/output name/type/confidence/authority/value/lineage; all ID tuples lexical |
| evidence node | evidence ID, source enum, provenance string and datetime-or-null node |
| assumption node | assumption ID, description string and materiality enum |
| caller limitation node | all caller fields; related ID tuples lexical; description string-or-null node |
| root `contradictions` | every `ContradictionInput`, contradiction-ID lexical; `left` and `right` positions preserved and encoded as the exact side records below |

The recursive record nodes have these exact keys; no additional key exists:

| Node | Canonical keys -> source/transformation |
| --- | --- |
| result | `result_id` -> canonical ID string; `module_id`, `module_status`, `evidence_sufficiency` -> enum nodes; `claims`, `evidence`, `assumptions`, `limitations` -> array nodes in respective ID order; `failure_reasons`, `blocking_reasons` -> enum-node arrays by enum value; `handoff_module_ids` -> enum-node array by `ModuleId.value` |
| claim | `claim_id` -> ID string; `declared_output_name` -> string node; `claim_type`, `confidence`, `authority_status`, `lineage_type` -> enum nodes; `value` -> generic tagged scalar; `parent_claim_ids`, `evidence_ids`, `assumption_ids`, `limitation_ids` -> ID-string array nodes in lexical order |
| evidence | `evidence_id` -> ID string; `source_class` -> enum node; `provenance` -> string node; `observed_at` -> datetime node or null node |
| assumption | `assumption_id` -> ID string; `description` -> string node; `materiality` -> enum node |
| caller limitation | `limitation_id` -> ID string; `reason`, `materiality` -> enum nodes; `related_result_ids`, `related_claim_ids`, `related_contradiction_ids` -> ID-string array nodes in lexical order; `description` -> string node or null node |
| contradiction input | exactly `contradiction_id` -> ID string; `left`, `right` -> side record nodes in caller position; no old shared or duplicate flat fields |
| contradiction side | exactly `claim_id` -> ID string; `evidence_id` -> ID string or null node; `object_key`, `segment_key`, `period_key`, `metric_definition_key` -> string nodes |

Fields declared order-significant preserve their frozen tuple order; all other order is exactly stated above. Contradiction `left` and `right` are order-significant and are never sorted: changing any side field or swapping sides changes the fingerprint. The source contains every caller-supplied contract field and excludes `batch_fingerprint`, all gate/contradiction output records, derived limitations, exclusions, decision requests/results, manifest and readiness. No cycle exists. The resulting lowercase 64-hex fingerprint is derived only. Equal normalized input is byte-identical; changing a caller contract value changes the preimage. Every output copies batch ID/fingerprint and both must match across stages.

Encode derived-ID preimage components as `<UTF-8-byte-length>:<UTF-8-bytes>` and concatenate. A contradiction limitation uses `quality-gates-v1`, `limitation`, fingerprint, result ID, contradiction ID, `UNRESOLVED_CONTRADICTION`; ID is `lim_` plus the first 32 lowercase SHA-256 hex characters. It is material, relates to that result, unique lexical affected claims and contradiction, and has no description. An exclusion uses `quality-gates-v1`, `exclusion`, fingerprint, subject type, result-or-empty, claim-or-empty, reason, contradiction-or-empty; empty encodes `0:` and ID is `exc_` plus the first 32 hex characters. Identical preimages deduplicate; different preimages producing one ID raise. Derived records sort by ID.

## Timestamp and freshness rules

Only exact built-in timezone-aware `datetime` is accepted; subclasses, naive values and strings are rejected. Any explicit UTC offset is accepted and normalized internally to UTC with microseconds preserved. Canonical serialization is ISO-8601 UTC ending in `Z`. No parsing from text occurs.

Evaluation never reads `datetime.now()`, `utcnow()`, system/local timezone, filesystem or environment time. `evaluation_at`, when supplied, is normalized identically but does not make absent evidence timestamps comparable. Comparing `observed_at` values yields `NEWER`, `OLDER`, `SAME`, or `UNKNOWN`: compare normalized instants when both exist; either absent yields `UNKNOWN`; equal instants yield `SAME`.

## Ordered validation and error containment

Validation order and first-error precedence are fixed:

1. exact outer contract type;
2. exact scalar/container type before iteration/lookup;
3. reject subclasses, custom Mapping/Sequence/Set, proxies and unsupported objects;
4. validate/copy/freeze accepted built-ins;
5. enum, ID, scalar, fingerprint and datetime value rules;
6. all namespace uniqueness, in field order then lexical ID order;
7. reference resolution, including selected-evidence membership, in result/field/ID order;
8. safe injected Registry lookup: producer, declared output, handoff;
9. module-status coherence;
10. derive canonical fingerprint and base gate outcome;
11. propagate, evaluate contradictions, create collision-checked derived records, adjust contradictions, derive final decision and manifest.

No untrusted object is iterated, sorted, hashed, compared, formatted, copied, represented or used in lookup before exact-type acceptance. Caller-created proxies are rejected without backing access. Internal frozen values resubmitted as caller inputs are not trusted.

Caller-caused `TypeError`, `ValueError`, `KeyError`, `OverflowError`, datetime errors and expected Registry lookup errors are converted to `QualityGateContractError` with safe field/accepted-ID/enum messages and exception chaining. `BaseException`, system exits and unexpected programmer defects are not caught. Raw hostile values never enter messages. Malformed input therefore leaks no incidental Python exception.

## Registry validation

The injected Registry must be version `1.0.0` with zero bindings. Producer uses exact `ModuleId`; no alias/string normalization occurs in normalized contracts. Each `declared_output_name` must exactly equal one output in the producer descriptor. Handoffs must be registered and exactly present in that descriptor's handoffs. Registry prose is never parsed into authority policy and no required-output schema is inferred.

## Complete gate derivation

Callers supply only module status and normalized content. Structural validity, readiness, eligibility and outcomes are derived. `OUT_OF_SCOPE` authority is never accepted. Non-material limitations are legal with `PASS`.

| Supplied status | Claims | Sufficiency | Material limitation | Failure reasons | Blocking reasons | Authority | Base outcome |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `PASS` | >=1 | `SUFFICIENT` | none | none | none | every claim `WITHIN_SCOPE` or `REQUIRES_REVIEW` | `PASS` |
| `PASS_WITH_LIMITATIONS` | >=1 | `SUFFICIENT` or `LIMITED` | >=1 | none | none | no claim `OUT_OF_SCOPE` | `PASS_WITH_LIMITATIONS` |
| `FAIL` | empty claim tuple; failure reasons are the only diagnostics | `INSUFFICIENT` or `NOT_ASSESSED` | any | >=1 | none | n/a | `FAIL` |
| `BLOCKED` | none | `NOT_ASSESSED` | any | none | >=1 | any | `BLOCKED` |

All other combinations raise. Explicit first-error order after earlier phases is: both failure+blocking reasons; executable/readiness injection; `OUT_OF_SCOPE` accepted status; missing required reason; forbidden reason; claim-presence rule; evidence-sufficiency rule; material-limitation rule; then remaining coherence. Explicitly invalid: `PASS` with material limitation; limited status without one; accepted status with `INSUFFICIENT`/`NOT_ASSESSED`; `FAIL`/`BLOCKED` synthesis injection; `FAIL` without failure; `BLOCKED` without blocker; and any caller-supplied/`EXECUTABLE` readiness.

Contradiction adjustment preserves every claim. Unresolved/incomparable claims receive one exclusion per claim/contradiction and one derived limitation per affected result/contradiction. Prioritized non-preferred claims receive `CONTRADICTION_PRECEDENCE` exclusion without a limitation. A claim with any exclusion is excluded; preferred status elsewhere cannot override it. If none remain, outcome is `FAIL/NO_USABLE_CLAIMS`; otherwise acceptance is limited when unresolved/incomparable limitations exist.

## Confidence and propagation

`ORIGINAL` requires no parents. `REPEATS`, `REFORMULATES` and `DERIVES` require one or more resolved parent claims. No text similarity exists. Repeated/reformulated confidence cannot exceed every parent; multi-parent derived confidence cannot exceed the minimum parent under the canonical order. If any parent is `UNKNOWN`, the ceiling is `UNKNOWN`. Original claims retain caller confidence, which gates do not certify. New evidence is retained but never permits an increase. Evidence independence remains deferred.

Propagation unions provenance, assumptions and limitations by stable ID, rejects unequal collisions, removes duplicate references and emits lexical ID order. It is order-independent and idempotent.

## Contradiction algorithm

Validate and resolve both exact `ContradictionSide` values first. Their claim IDs must differ; each selected evidence ID must resolve and belong to that side's claim; both evidence IDs must be present or both `None`. Compare `object_key`, `segment_key`, `period_key` and `metric_definition_key` pairwise by exact validated-string equality in that order. If any pair differs, state is `INCOMPARABLE`; evidence precedence is not evaluated and preferred claim/reason are absent. Only when all four pairs match is evidence considered: both selected IDs absent or the same selected ID yields `UNRESOLVED`; exactly one side is prioritized only when its selected source is `FIRST_PARTY`, the other is `GENERIC_BENCHMARK`, both timestamps exist, and first-party is `SAME` or `NEWER`; reason is `FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK`. Every other comparable case is `UNRESOLVED`. Reversing sides preserves semantic state and preferred claim but, because caller positions are preserved, produces a distinct batch fingerprint.

The evaluator never chooses or aggregates evidence. Unselected evidence cannot affect precedence. Source ranking, majority, minimum/maximum, newest search and averaging are prohibited. Both claims and all evidence remain preserved.

## Gate × decision compatibility

Trigger validation occurs after final gate derivation. Duplicate values in list/tuple inputs are contract errors; exact set/frozenset inputs are already unique. Output order is enum-value lexical.

| Final gate | Legal decision |
| --- | --- |
| `BLOCKED` | exactly `BLOCKED` with matching non-empty blocking reasons; stop/replan triggers illegal |
| `FAIL` | exactly `STOP` + `RESULT_FAILED`; blocking/replan triggers illegal |
| `PASS`/`PASS_WITH_LIMITATIONS` | blocking reasons illegal; use precedence below |

Accepted-gate precedence: (1) `SCOPE_COMPLETE` or `SUFFICIENT_EVIDENCE` -> `STOP`; (2) `MATERIAL_FINDING`, `DEPENDENCY_INVALIDATED` or `REVERSIBLE_TEST_HIGHER_VALUE` -> `REPLAN_REQUIRED`; (3) `DIMINISHING_VALUE`, `TOOL_LIMIT_REACHED` or `CAPABILITY_LIMIT_REACHED` -> `STOP`; (4) no trigger -> `CONTINUE_CURRENT_PLAN`. Multiple reasons within the winning tier are retained in enum order; lower-tier reasons are retained as evaluated triggers but cannot alter the decision. Any incompatible combination raises.

No decision generates a plan, invokes a module, persists or mutates anything.

## Synthesis eligibility manifest

The complete manifest above is identified only by batch ID/fingerprint. Every result is evaluated once; only eligible accepted results/claims contribute; exclusions are exhaustive and non-overlapping. Exclusion is not deletion. It generates no prose, raw dump, hidden reasoning or public DTO.

## Risks / Trade-offs

- Strict contracts require future adapters -> intentionally defer adapters rather than silently accepting legacy dictionaries.
- Conservative confidence may understate strong new evidence -> future reviewed independence policy can extend it.
- Registry output membership is not completeness -> defer module schemas instead of inventing them.
- Large contract surface -> split tasks and durable verification evidence by invariant.

## Migration and rollback

No migration or rollout integration exists. Runtime apply adds only an unused internal package and tests. Rollback removes that package and documentation; current behavior is unchanged.
