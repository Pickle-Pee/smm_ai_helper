# Design: Deterministic orchestrator quality gates

## Context and boundary

This change adds a side-effect-free internal foundation after planning and before future workflow synthesis. It accepts an already-constructed `NormalizedModuleResult`, Registry `1.0.0`, and optional typed contradiction/decision inputs; it returns immutable decisions. It never executes modules, fetches context, persists state, creates a plan, generates prose or calls a model/QC service.

The current `ModuleResult` is lightweight Registry metadata and existing agents return unrelated dictionaries. Neither is silently reinterpreted. Future adapters must explicitly map a source contract into this boundary.

## Exact construction and immutability

All public contracts are frozen, slotted dataclasses. Constructors accept only exact built-in types, never subclasses or structural substitutes:

- scalar: `None`, `bool`, `int`, finite `float`, or `str`; booleans are never accepted as integers;
- ordered container: exact `tuple` or `list`, copied to tuple;
- semantic set: exact `set`, `frozenset`, `tuple`, or `list`, copied to a deterministically ordered tuple/frozenset as declared;
- mappings are not accepted in normalized result fields;
- stable IDs are non-empty lowercase identifiers matching `^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$`, maximum 128 characters;
- prose fields are exact non-empty strings and never serve as machine identifiers;
- numeric confidence is an exact finite float in `[0.0, 1.0]`.

Every nested element is exact-type checked before use and defensively copied. Unsupported values, duplicate IDs, dangling references and illegal state combinations raise `QualityGateContractError`; malformed input never becomes a gate `FAIL` or `BLOCKED` result. Re-evaluating equal values returns an equal decision and has no side effects.

## Normalized result model

The immutable boundary contains:

- `result_id`, canonical `module_id`, and `module_status` (`ModuleResultStatus`);
- `claims: tuple[NormalizedClaim, ...]` with stable `claim_id`, `ClaimType`, exact scalar `value`, optional unit/display statement, stable `evidence_ids`, stable `assumption_ids`, confidence and declared Registry output name;
- `evidence: tuple[EvidenceRecord, ...]` with stable `evidence_id`, typed `SourceClass`, non-empty provenance reference, optional exact UTC timestamp/freshness class and optional source claim ID;
- `assumptions: tuple[AssumptionRecord, ...]` with stable ID, statement and explicit materiality;
- `limitations: tuple[LimitationRecord, ...]` with stable ID, typed reason, statement, materiality and affected claim IDs;
- `failure_reasons` or `blocking_reasons`, each typed and required only for its legal status;
- optional typed `handoff_module_ids`;
- `evidence_sufficiency`, explicit authority declarations and `execution_readiness` fixed to `PLANNING_ONLY`.

Claim, evidence, assumption and limitation IDs are unique and all references resolve. Evidence provenance is never optional. Claim prose/value does not become an identifier. Registry output strings may validate a claim's declared output membership, but Registry metadata does not say which outputs are required for every invocation; module-specific completeness is deferred.

Authority checking is structural only: canonical producer identity, declared output membership where supplied, and registered handoff membership. Registry prose authority limitations are not interpreted as executable policy.

## Distinct state dimensions

These types are never overloaded: `ModuleResultStatus`, `StructuralValidity`, `GateOutcome`, `EvidenceSufficiency`, numeric claim confidence, material limitations, `ContradictionState`, `NextStepDecision`, `StopDecision`, `ExecutionReadiness`, and synthesis eligibility/exclusion reason.

Structurally invalid input raises `QualityGateContractError`; therefore every returned decision has `StructuralValidity.VALID`.

## Legal-state matrix

| Module status | Required legal content | Forbidden combination | Gate outcome | Future synthesis |
| --- | --- | --- | --- | --- |
| `PASS` | at least one claim; `SUFFICIENT`; no material limitation; no failure/block reason | missing provenance, material limitation, insufficient evidence | `PASS` | eligible claims unless unresolved contradiction excludes them |
| `PASS_WITH_LIMITATIONS` | at least one usable claim; at least one material limitation; `PARTIAL` or `INSUFFICIENT` | no material limitation, failure/block reason | `PASS_WITH_LIMITATIONS` | eligible with every material limitation preserved |
| `FAIL` | at least one typed failure reason; no accepted claims or handoff | missing failure reason, blocking reason, synthesis eligibility | `FAIL` | excluded as `FAILED_RESULT` |
| `BLOCKED` | at least one typed blocking reason identifying missing input or capability; no accepted claims or handoff | absent blocker, failure reason, success eligibility | `BLOCKED` | excluded as `BLOCKED_RESULT` |

An explicit, complete `FAIL` is a valid unusable result. A complete `BLOCKED` is a valid non-execution result caused by a typed blocker. Missing required normalized fields, contradictory combinations, unknown modules, illegal handoffs or dangling identities are contract errors, not outcomes. A complete structure is evidence only of contract validity, never claim truth.

## Evidence, confidence and limitation propagation

- IDs and provenance are preserved exactly; propagation unions by stable ID, rejects unequal records sharing an ID, and emits deterministic ID order.
- Assumptions remain assumptions and are never converted to claims/facts.
- Every material limitation affecting an accepted result or claim is copied to downstream packets/manifests.
- Repetition or reformulation retains the source claim ID and may keep or lower confidence, never raise it.
- New evidence may be attached, but this foundation cannot verify independence or truth; therefore confidence never increases here. A future reviewed contract may add a structural independence assertion and a separate policy.
- Combining claims creates a new stable claim ID with explicit source claim IDs; its confidence cannot exceed the minimum confidence of required source claims.
- Set-like propagation is order-independent; semantically meaningful source ordering remains explicit.

## Contradictions and precedence

Contradictions are caller-supplied `ContradictionRecord` values; gates never search prose. Each record contains stable ID, compared claim IDs, typed object/segment/period/metric-definition keys, source classes, freshness/timestamps, `ContradictionState`, and optional typed precedence reason/winning claim ID.

Both claims remain present and values are never averaged. Different object, segment, period or metric-definition keys make claims incomparable and the record remains `UNRESOLVED`. Current first-party evidence may receive `CURRENT_FIRST_PARTY` precedence over an explicitly generic benchmark only when comparison keys match and freshness is explicitly comparable. Equal class/freshness, missing freshness, multiple eligible winners or any tie remains unresolved. Precedence never deletes or proves either claim.

## Replanning and stop decisions

Pure evaluation accepts explicit `DecisionTrigger` enums only. Precedence is:

1. missing blocking input or unavailable capability -> `BLOCKED`;
2. failed module result -> `STOP` with `FAILED_MODULE_RESULT`;
3. invalidated dependency or accepted material finding -> `REPLAN_REQUIRED`;
4. sufficient decision evidence, diminishing additional value or preference for a reversible test -> `STOP` with the corresponding reason;
5. otherwise -> `CONTINUE_CURRENT_PLAN`.

Stopping records a decision only; it does not imply execution. `REPLAN_REQUIRED` requests a future plan and neither mutates the existing plan/findings nor creates or executes a revision. Invalid contracts raise before decision evaluation. No additional module is invoked by this foundation.

## Synthesis eligibility

The optional `SynthesisEligibilityManifest` is data, not synthesis. It deterministically lists accepted result IDs, accepted claim IDs, all material limitations, unresolved contradiction IDs, and excluded result IDs with typed reasons. `FAIL`/`BLOCKED` results are excluded; limited accepted claims retain limitations; unresolved contradictory claims are preserved but marked unresolved. The manifest contains no generated prose, raw module dump, presentation schema or chain-of-thought.

## Architectural isolation

- `QCService` remains model-based editorial QC and is not reused.
- `AgentRegistry`, agents, result dictionaries, `AgentOutputBuilder`, presenters and public DTOs remain unchanged.
- `TaskPipelineService`, routers and Telegram remain unchanged.
- No database session or `MarketingWorkflowPersistenceService` is relevant; no transaction ownership is introduced.
- Registry `1.0.0` remains the canonical metadata resource with zero bindings.
- Marketing Orchestrator plans remain `PLANNING_ONLY`.
- Product prompt documents remain source material and are not loaded or copied into Python.

## Verification strategy

Deterministic unit tests cover every legal matrix row, exact/subclass rejection, deep immutability, duplicate/dangling IDs, hostile containers, non-finite confidence, unknown modules, illegal handoffs, propagation collisions/order, conservative confidence, limitations, contradictions/ties, decision precedence, manifests, idempotency and forbidden-call isolation. Verification also proves existing agents/presenters/public DTOs and planner/Registry contracts are unchanged and no LLM/QC/persistence/Redis/worker call occurs.

