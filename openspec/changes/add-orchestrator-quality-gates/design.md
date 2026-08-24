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
- `ExclusionReason`: `RESULT_FAILED`, `RESULT_BLOCKED`, `UNRESOLVED_CONTRADICTION`.
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

Comparison keys (`object_key`, `segment_key`, `period_key`, `metric_definition_key`) are exact non-empty ASCII strings matching `^[a-z0-9][a-z0-9_.:-]{0,127}$`; they are never derived from prose.

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
| `LimitationRecord.limitation_id` | prefixed `str` | required | unique batch-wide | caller |
| `.reason/.materiality` | `LimitationReason`, `Materiality` | required | exact enums | caller or derived |
| `.related_result_ids` | tuple of `ResultId` | default `()` | unique lexical; batch-resolved | caller or derived |
| `.related_claim_ids` | tuple of `ClaimId` | default `()` | unique lexical; batch-resolved; caller limitation must reference a result or claim | caller or derived |
| `.related_contradiction_ids` | tuple of `ContradictionId` | default `()` | unique lexical; batch-resolved | caller or derived |
| `.description` | exact non-empty `str | None` | default `None` | derived contradiction limitation is `None` | caller or derived |
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
| `ContradictionInput.contradiction_id` | prefixed `str` | required | unique batch-wide | caller |
| `.left_claim_id` | `ClaimId` | required | batch-resolved | caller |
| `.right_claim_id` | `ClaimId` | required | batch-resolved and distinct | caller |
| `.left_evidence_id` | `EvidenceId | None` | default `None` | paired presence; belongs to left claim | caller |
| `.right_evidence_id` | `EvidenceId | None` | default `None` | paired presence; belongs to right claim | caller |
| `.object_key` | comparison-key `str` | required | exact comparison | caller |
| `.segment_key` | comparison-key `str` | required | exact comparison | caller |
| `.period_key` | comparison-key `str` | required | exact comparison | caller |
| `.metric_definition_key` | comparison-key `str` | required | exact comparison | caller |
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
| `ContradictionRecord` | `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `contradiction_id: ContradictionId`; `left_claim_id: ClaimId`; `right_claim_id: ClaimId`; `left_evidence_id: EvidenceId|None=None`; `right_evidence_id: EvidenceId|None=None`; `state: ContradictionState`; `preferred_claim_id: ClaimId|None=None`; `precedence_reason: ContradictionPrecedenceReason|None=None`; `preserved_claim_ids: tuple[ClaimId,ClaimId]`; `excluded_claim_ids: tuple[ClaimId,...]=()`; `derived_limitation_ids: tuple[LimitationId,...]=()` |
| `ExclusionRecord` | `exclusion_id: ExclusionId`; `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `subject_type: ExclusionSubjectType`; `result_id: ResultId|None=None`; `claim_id: ClaimId|None=None`; `reason: ExclusionReason`; `contradiction_id: ContradictionId|None=None`; `related_limitation_ids: tuple[LimitationId,...]=()` |
| `DecisionRequest` | `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `gate_decision: GateDecision`; `replan_reasons: frozenset[ReplanReason]=frozenset()`; `stop_reasons: frozenset[StopReason]=frozenset()`; `blocking_reasons: frozenset[BlockingReason]=frozenset()` |
| `DecisionResult` | `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `result_id: ResultId`; `gate_outcome: GateOutcome`; `decision: ReplanningDecision`; `replan_reasons: tuple[ReplanReason,...]=()`; `stop_reasons: tuple[StopReason,...]=()`; `blocking_reasons: tuple[BlockingReason,...]=()`; `execution_readiness: ExecutionReadiness` |
| `SynthesisEligibilityManifest` | `batch_id: BatchId`; `batch_fingerprint: BatchFingerprint`; `evaluated_result_ids: non-empty tuple[ResultId,...]`; `accepted_result_ids: tuple[ResultId,...]=()`; `accepted_claim_ids: tuple[ClaimId,...]=()`; `limitation_ids: tuple[LimitationId,...]=()`; `unresolved_contradiction_ids: tuple[ContradictionId,...]=()`; `exclusions: tuple[ExclusionRecord,...]=()`; `execution_readiness: ExecutionReadiness` |

All are frozen/slotted. `GateDecision` fields are copied or derived exactly as named: emitted validity is `VALID`; readiness is `PLANNING_ONLY`; accepted/excluded claims are disjoint; preserved evidence/assumption/limitation IDs are batch-resolved; `FAIL` has non-empty failure reasons and no accepted claims; `BLOCKED` has non-empty blockers and no accepted claims. Its authority is `WITHIN_SCOPE` if every accepted claim is within scope, otherwise `REQUIRES_REVIEW`; empty-claim failed/blocked results use `WITHIN_SCOPE`. `(batch_id, batch_fingerprint, result_id)` is the decision identity and no separate ID exists.

`INCOMPARABLE`/`UNRESOLVED` contradiction records have no preferred claim/reason, exclude both claims, and contain derived limitation IDs. `PRIORITIZED` has exactly one preferred claim and `FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK`, excludes neither claim in the record, preserves both, and permits only the preferred claim into unqualified accepted IDs.

An exclusion has exactly one of result/claim ID. Failed result produces `RESULT_FAILED`; blocked result produces `RESULT_BLOCKED`; unresolved/incomparable claim produces `UNRESOLVED_CONTRADICTION` with contradiction and related limitation. These paths are exhaustive and non-overlapping.

`DecisionRequest` accepts only exact built-in containers before freezing and exact enums; duplicates are rejected. Its batch ID and fingerprint must both equal the exact evaluator-produced gate decision. `DecisionResult` uses the matrix below for tuple emptiness and identity. One manifest is identified by `(batch_id, batch_fingerprint)`; every result occurs once in evaluated IDs, failed/blocked results are not accepted, unresolved claims are not accepted, exclusions are exhaustive, and the output contains no prose or public DTO.

## Namespace and reference rules

One immutable `EvaluationBatch` owns all namespaces. Batch, result, claim, evidence, assumption, limitation and contradiction IDs have independent namespaces; exclusion IDs are unique in derived outputs. Duplicate validation completes before reference resolution.

Evidence, assumption and caller-limitation references are result-local. Lineage and contradiction claim references may cross results only inside the same batch. Selected evidence resolves in its claim's owning result and must occur in that claim's `evidence_ids`.

### Canonical batch fingerprint and derived IDs

After normalization, serialize every contract-relevant batch value except `batch_fingerprint` as canonical UTF-8 JSON: sorted object keys; enum `.value`; IDs unchanged; UTC `Z` timestamps preserving microseconds; order-significant tuples preserved; set-like collections lexically sorted; no whitespace or locale formatting. Lowercase SHA-256 hex is the fingerprint. Every derived output copies batch ID/fingerprint; both must match across stages.

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

Contradiction adjustment preserves every claim. Unresolved/incomparable claims receive one exclusion per claim/contradiction and one limitation per affected result/contradiction. If none remain, outcome is `FAIL/NO_USABLE_CLAIMS`; otherwise acceptance is limited. For prioritized contradictions, both remain preserved but only the preferred claim may be unqualified accepted.

## Confidence and propagation

`ORIGINAL` requires no parents. `REPEATS`, `REFORMULATES` and `DERIVES` require one or more resolved parent claims. No text similarity exists. Repeated/reformulated confidence cannot exceed every parent; multi-parent derived confidence cannot exceed the minimum parent under the canonical order. If any parent is `UNKNOWN`, the ceiling is `UNKNOWN`. Original claims retain caller confidence, which gates do not certify. New evidence is retained but never permits an increase. Evidence independence remains deferred.

Propagation unions provenance, assumptions and limitations by stable ID, rejects unequal collisions, removes duplicate references and emits lexical ID order. It is order-independent and idempotent.

## Contradiction algorithm

Resolve claims and compare all four keys; any difference is `INCOMPARABLE`. Both selected evidence IDs absent is `UNRESOLVED`; one absent is a contract error. Resolve the explicitly selected evidence and verify claim membership. The same selected ID on both sides is `UNRESOLVED`. Exactly one side is prioritized only when its selected source is `FIRST_PARTY`, the other is `GENERIC_BENCHMARK`, both timestamps exist, and first-party is `SAME` or `NEWER`; reason is `FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK`. Every other case is `UNRESOLVED`.

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
