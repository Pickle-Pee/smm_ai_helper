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
- `ContradictionPrecedenceReason`: `FIRST_PARTY_NOT_OLDER_THAN_GENERIC_BENCHMARK`.
- `FreshnessComparison`: `NEWER`, `OLDER`, `SAME`, `UNKNOWN`.
- `ExclusionReason`: `RESULT_FAILED`, `RESULT_BLOCKED`, `UNRESOLVED_CONTRADICTION`, `NOT_SYNTHESIS_ELIGIBLE`.
- `ReplanningDecision`: `CONTINUE_CURRENT_PLAN`, `REPLAN_REQUIRED`, `STOP`, `BLOCKED`.
- `ReplanReason`: `MATERIAL_FINDING`, `DEPENDENCY_INVALIDATED`, `REVERSIBLE_TEST_HIGHER_VALUE`.
- `StopReason`: `SCOPE_COMPLETE`, `SUFFICIENT_EVIDENCE`, `DIMINISHING_VALUE`, `TOOL_LIMIT_REACHED`, `CAPABILITY_LIMIT_REACHED`, `RESULT_FAILED`.

## Exact scalar, container and ID domain

Caller scalars are exact built-in `None`, `bool`, `int`, finite `float`, or `str`; bool is never accepted where int is required. Prose is exact non-empty `str`. Ordered fields accept exact `list` or `tuple`, are validated item-first and copied to tuple. Semantic sets accept exact `list`, `tuple`, `set` or `frozenset`, reject duplicates before freezing, and emit enum/ID lexical order. Exact dictionaries are allowed only for fields explicitly declared as mappings, require exact string keys, and become copied internal mapping proxies. No contract below currently exposes a caller mapping field. Mapping proxies are output-only and rejected if resubmitted.

Entity IDs are exact ASCII built-in strings, are not trimmed/case-folded/normalized, have maximum length 67, and match:

```regex
^(res|clm|evd|asm|lim|ctr|exc|man)_[a-z0-9][a-z0-9_-]{0,62}$
```

Field prefixes are mandatory: result `res_`, claim `clm_`, evidence `evd_`, assumption `asm_`, limitation `lim_`, contradiction `ctr_`, exclusion `exc_`, manifest `man_`. The `man_` extension is required because the manifest itself has identity. Wrong prefixes and duplicate IDs are errors even when bodies/records are equal.

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
| `.reason/.description/.materiality` | enum, `str`, enum | required | description non-empty | caller |
| `.affected_claim_ids` | tuple of claim IDs | required | non-empty, lexical | caller |
| `NormalizedClaim.claim_id` | prefixed `str` | required | unique batch-wide | caller |
| `.declared_output_name` | exact non-empty `str` | required | exact Registry membership | caller |
| `.claim_type/.confidence/.authority_status` | respective enums | required | n/a | caller |
| `.value` | exact scalar | required | string may be empty only as a scalar value | caller |
| `.lineage_type` | `ClaimLineageType` | required | n/a | caller |
| `.parent_claim_ids` | tuple of claim IDs | default `()` | lexical; rules below | caller |
| `.evidence_ids/.assumption_ids/.limitation_ids` | respective ID tuples | default `()` | lexical, unique | caller |
| `NormalizedModuleResult.result_id` | prefixed `str` | required | unique batch-wide | caller |
| `.module_id/.module_status` | `ModuleId`, `ModuleResultStatus` | required | n/a | caller |
| `.claims/.evidence/.assumptions/.limitations` | exact typed sequences | default `()` | ID lexical | caller |
| `.failure_reasons/.blocking_reasons` | enum semantic sets | default empty | enum declaration order | caller |
| `.evidence_sufficiency` | `EvidenceSufficiency` | required | n/a | caller |
| `.handoff_module_ids` | semantic set of `ModuleId` | default empty | ModuleId value order | caller |
| `ContradictionInput.contradiction_id` | prefixed `str` | required | unique batch-wide | caller |
| `.left_claim_id/.right_claim_id` | claim IDs | required | distinct, resolved | caller |
| `.object_key/.segment_key/.period_key/.metric_definition_key` | comparison keys | required | exact comparison | caller |
| `EvaluationBatch.results` | tuple of results | required | non-empty, result-ID order | caller |
| `.contradictions` | tuple of inputs | default `()` | contradiction-ID order | caller |
| `.evaluation_at` | exact aware `datetime | None` | default `None` | normalized UTC; metadata only | caller |
| `ExclusionRecord.exclusion_id` | prefixed `str` | required | unique batch-wide | derived |
| `.result_id/.claim_id` | result ID, claim ID or `None` | exactly one required | resolved | derived |
| `.reason` | `ExclusionReason` | required | n/a | derived |
| `GateDecision` state fields | validity, outcome, readiness, eligibility | required | immutable | derived |
| `ContradictionRecord` input fields plus state/reason/winner | typed values | required; reason/winner optional together | both claims preserved | derived |
| `DecisionRequest.gate_decision` | `GateDecision` | required | same batch | caller from prior output |
| `.replan_reasons/.stop_reasons` | semantic enum sets | default empty | enum order, deduplicated | caller |
| `.blocking_reasons` | semantic set | default empty | enum order | caller |
| `DecisionResult` decision/replan reason/stop reason | typed values | required/optional by matrix | no contradictory reasons | derived |
| `SynthesisEligibilityManifest.manifest_id` | prefixed `str` | required | unique batch-wide | caller identity, content derived |
| remaining manifest fields | resolved ID tuples, limitations, exclusions | required | lexical ID order | derived |

No caller supplies structural validity, `GateOutcome`, execution readiness, synthesis eligibility, contradiction state/precedence, exclusion records or manifest content.

## Namespace and reference rules

One immutable `EvaluationBatch` owns all namespaces. Result IDs are unique; claim/evidence/assumption/limitation IDs are each unique across every included result; contradiction IDs are unique across the batch; exclusion/manifest IDs are unique in derived outputs. Duplicate validation completes for all namespaces before any reference is resolved, so duplicate identity always wins over unresolved-reference errors.

Result-local references resolve within their result unless explicitly documented as lineage. Parent claim lineage and contradiction claim references may cross results only when the target is present in the same batch. All evidence, assumption, limitation, lineage, contradiction and manifest references resolve; unknown/external IDs fail. Unequal records can never share an ID.

## Timestamp and freshness rules

Only exact built-in timezone-aware `datetime` is accepted; subclasses, naive values and strings are rejected. Any explicit UTC offset is accepted and normalized internally to UTC with microseconds preserved. Canonical serialization is ISO-8601 UTC ending in `Z`. No parsing from text occurs.

Evaluation never reads `datetime.now()`, `utcnow()`, system/local timezone, filesystem or environment time. `evaluation_at`, when supplied, is normalized identically but does not make absent evidence timestamps comparable. Comparing `observed_at` values yields `NEWER`, `OLDER`, `SAME`, or `UNKNOWN`: compare normalized instants when both exist; either absent yields `UNKNOWN`; equal instants yield `SAME`.

## Ordered validation and error containment

Validation order and first-error precedence are fixed:

1. exact outer contract type;
2. exact scalar/container type before iteration/lookup;
3. reject subclasses, custom Mapping/Sequence/Set, proxies and unsupported objects;
4. validate/copy/freeze accepted built-ins;
5. enum, ID, scalar and datetime value rules;
6. all namespace uniqueness, in field order then lexical ID order;
7. reference resolution, in result/field/ID order;
8. safe injected Registry lookup: producer, declared output, handoff;
9. module-status coherence;
10. derive base gate outcome;
11. propagate, evaluate contradictions, apply contradiction adjustment, derive final decision and manifest eligibility.

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

Contradiction adjustment is deterministic: preserve every claim. Unresolved/incomparable claims are excluded from accepted claim IDs with one derived exclusion each. If none remain, final outcome is `FAIL`, eligibility is `INELIGIBLE`, and derived reason includes `NO_USABLE_CLAIMS`. If some remain, an otherwise accepted result becomes/remains `PASS_WITH_LIMITATIONS` with a derived material `UNRESOLVED_CONTRADICTION` limitation. This adjustment resolves the distinction between preservation and eligibility.

## Confidence and propagation

`ORIGINAL` requires no parents. `REPEATS`, `REFORMULATES` and `DERIVES` require one or more resolved parent claims. No text similarity exists. Repeated/reformulated confidence cannot exceed every parent; multi-parent derived confidence cannot exceed the minimum parent under the canonical order. If any parent is `UNKNOWN`, the ceiling is `UNKNOWN`. Original claims retain caller confidence, which gates do not certify. New evidence is retained but never permits an increase. Evidence independence remains deferred.

Propagation unions provenance, assumptions and limitations by stable ID, rejects unequal collisions, removes duplicate references and emits lexical ID order. It is order-independent and idempotent.

## Contradiction algorithm

Claims are comparable only when object, segment, period and metric-definition keys match exactly; otherwise state is `INCOMPARABLE`. Comparable claims preserve both and are never averaged.

The only prioritization rule is: one side has explicit `FIRST_PARTY`, the other explicit `GENERIC_BENCHMARK`, both `observed_at` exist, and first-party is `SAME` or `NEWER`. State becomes `PRIORITIZED`, winner is the first-party claim and reason is `FIRST_PARTY_NOT_OLDER_THAN_GENERIC_BENCHMARK`. Missing timestamps, older first-party, equal source classes, ties and every uncovered case are `UNRESOLVED`. Recency within the same source class never creates precedence. Prioritization is decision precedence, not truth, and never deletes the other claim.

## Gate × decision compatibility

Trigger validation occurs after final gate derivation. Duplicate triggers deduplicate by enum identity and do not change output.

| Final gate | Legal decision |
| --- | --- |
| `BLOCKED` | exactly `BLOCKED` with matching non-empty blocking reasons; stop/replan triggers illegal |
| `FAIL` | exactly `STOP` + `RESULT_FAILED`; blocking/replan triggers illegal |
| `PASS`/`PASS_WITH_LIMITATIONS` | blocking reasons illegal; use precedence below |

Accepted-gate precedence: (1) `SCOPE_COMPLETE` or `SUFFICIENT_EVIDENCE` -> `STOP`; (2) `MATERIAL_FINDING`, `DEPENDENCY_INVALIDATED` or `REVERSIBLE_TEST_HIGHER_VALUE` -> `REPLAN_REQUIRED`; (3) `DIMINISHING_VALUE`, `TOOL_LIMIT_REACHED` or `CAPABILITY_LIMIT_REACHED` -> `STOP`; (4) no trigger -> `CONTINUE_CURRENT_PLAN`. Multiple reasons within the winning tier are retained in enum order; lower-tier reasons are retained as evaluated triggers but cannot alter the decision. Any incompatible combination raises.

No decision generates a plan, invokes a module, persists or mutates anything.

## Synthesis eligibility manifest

The immutable manifest contains `manifest_id`, all evaluated result IDs, accepted result IDs, accepted claim IDs, unresolved contradiction IDs, all applicable limitations and typed exclusion records. Every reference resolves inside the batch. Eligible `PASS` and `PASS_WITH_LIMITATIONS` results may contribute; `FAIL`/`BLOCKED` receive `RESULT_FAILED`/`RESULT_BLOCKED`; unresolved/incomparable claims receive `UNRESOLVED_CONTRADICTION`. Exclusion is not deletion. The manifest generates no prose, raw dump, hidden reasoning or public DTO.

## Risks / Trade-offs

- Strict contracts require future adapters -> intentionally defer adapters rather than silently accepting legacy dictionaries.
- Conservative confidence may understate strong new evidence -> future reviewed independence policy can extend it.
- Registry output membership is not completeness -> defer module schemas instead of inventing them.
- Large contract surface -> split tasks and durable verification evidence by invariant.

## Migration and rollback

No migration or rollout integration exists. Runtime apply adds only an unused internal package and tests. Rollback removes that package and documentation; current behavior is unchanged.
