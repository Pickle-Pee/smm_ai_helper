# Tasks

Authoritative implementation base: `607696ab02da7dafabfcdd0bfeb2f29724b80c38`.

## 1. Completed reconciliation evidence

- [x] 1.1 Verify Registry `1.0.0`, 15 descriptors, zero bindings and normalized checksum `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`.
- [x] 1.2 Verify existing planner/validator, `QCService`, agents, presenters, public DTOs, `AgentRegistry`, `TaskPipelineService` and persistence boundaries.
- [x] 1.3 Reconcile proposal, design, delta spec and product/architecture/governance documents as a planning-only contract.
- [x] 1.4 Create the durable pre-implementation verification template without claiming runtime implementation evidence.

## 2. Package and finite contracts

- [x] 2.1 Create `app/marketing_orchestrator/quality_gates/` with only the designed internal modules and minimal `__init__.py` exports.
- [x] 2.2 Implement every canonical enum and prove exact membership and absence of duplicate synonyms.
- [x] 2.3 Implement normalized caller result/claim/evidence/assumption contracts; prove their field tables and deep freeze independently.
- [x] 2.4 Implement caller `LimitationRecord`; prove caller ownership and absence of fingerprint cycles.
- [x] 2.5 Implement `GateDecision`; prove every field source set, empty policy and identity.
- [x] 2.6 Implement `ContradictionInput`; prove exact selected-evidence fields and membership rules.
- [x] 2.7 Implement `ContradictionRecord`; prove state-specific tuple coherence and batch association.
- [x] 2.8 Implement `DerivedLimitationRecord`; prove output-only ownership, references and batch association.
- [x] 2.9 Implement `ExclusionRecord`; prove subject coherence and all four closed reasons.
- [x] 2.10 Implement `BatchEvaluationResult`; prove one-to-one nested outputs, ordering and reference resolution.
- [x] 2.11 Implement `DecisionRequest`; prove exact trigger containers and batch/fingerprint match.
- [x] 2.12 Implement `DecisionResult`; prove matrix-specific fields and reason retention.
- [x] 2.13 Implement `SynthesisEligibilityManifest`; prove exact source sets and deep freeze.
- [x] 2.14 Reuse Registry `ModuleId` and `ModuleResultStatus`; add no competing module/status vocabulary.
- [x] 2.15 Implement immutable caller `ContradictionSide` with complete claim, optional evidence and four typed comparison-key fields; prove no duplicate key vocabulary.

## 3. Exact input and error boundary

- [x] 3.1 Validate exact scalar types and finite floats used only as claim scalar values; reject bool-as-int ambiguity.
- [x] 3.2 Validate exact list/tuple/set/frozenset/dict fields before access and defensively freeze accepted containers.
- [x] 3.3 Reject subclasses and custom Mapping/Sequence/Set values without invoking hostile methods.
- [x] 3.4 Reject caller-created mapping proxies without inspecting backing mappings; keep internal proxies output-only.
- [x] 3.5 Validate the prefixed ASCII ID regex, length and field-specific prefix for every ID.
- [x] 3.6 Validate caller batch/result/claim/evidence/assumption/limitation/contradiction namespaces independently; validate derived exclusion IDs without inventing manifest/decision IDs.
- [x] 3.7 Resolve all local/cross-result lineage, contradiction, limitation and manifest references after uniqueness validation.
- [x] 3.8 Normalize caller-caused supported Python/Registry errors and caller-construction failures to `QualityGateContractError` without catching programmer defects or `BaseException`.
- [x] 3.9 Add separate hostile-container tests across the complete caller graph proving validation performs no iteration, lookup, hashing, comparison, formatting, copying, `str()` or `repr()` before type acceptance.
- [x] 3.10 Add separate exception-boundary tests for construction/validation `TypeError`, `ValueError`, `KeyError`, `OverflowError`, datetime errors and expected public Registry lookup errors.
- [x] 3.11 Validate left/right side claim resolution, distinct claims, paired evidence presence and evidence membership before comparison.

## 4. Time and Registry validation

- [x] 4.1 Accept only exact aware `datetime` values, normalize them to UTC preserving microseconds and serialize with `Z`.
- [x] 4.2 Reject naive/subclass/string timestamps and prove no ambient clock/timezone/filesystem/environment time is read.
- [x] 4.3 Implement explicit observed-at comparison and `NEWER`/`OLDER`/`SAME`/`UNKNOWN` results.
- [x] 4.4 Validate canonical registered module identity through injected read-only Registry lookup.
- [x] 4.5 Validate each supplied declared output name by exact membership in its descriptor without inventing required-output schemas.
- [x] 4.6 Validate each handoff as a registered target and exact member of the producer descriptor's handoffs.
- [x] 4.7 Prove Registry remains version `1.0.0`, 15 descriptors and zero execution bindings.

## 5. Legal state and gate outcomes

- [x] 5.1 Implement the ordered validation phases and deterministic first-error precedence.
- [x] 5.2 Prove controlled construction rejects caller-supplied structural validity, gate outcome, execution readiness, synthesis eligibility and every derived field with `QualityGateContractError`.
- [x] 5.3 Implement and test exact `PASS` derivation, including non-material limitations.
- [x] 5.4 Implement and test exact `PASS_WITH_LIMITATIONS` derivation and required material limitation.
- [x] 5.5 Implement and test structurally valid `FAIL` with an empty claim tuple and required typed failure reason.
- [x] 5.6 Implement and test legitimate `BLOCKED`, `NOT_ASSESSED` and required blocking reason.
- [x] 5.7 Reject every enumerated illegal status/evidence/limitation/reason/authority/claim combination.
- [x] 5.8 Reject executable readiness under Registry `1.0.0`; derive `PLANNING_ONLY` only.
- [x] 5.9 Prove equal evaluation batches yield equal complete aggregates/decisions and no side effects.

## 6. Propagation and contradictions

- [x] 6.1 Implement explicit acyclic `ORIGINAL`/`REPEATS`/`REFORMULATES`/`DERIVES` lineage validation.
- [x] 6.2 Propagate evidence provenance into evaluator outputs by ID with collision rejection, deduplication and stable ordering.
- [x] 6.3 Propagate assumptions and material/non-material limitations into evaluator outputs without type conversion or loss.
- [x] 6.4 Enforce `UNKNOWN < LOW < MEDIUM < HIGH`, effective parent ceilings and multi-parent minimum confidence.
- [x] 6.5 Prove new evidence never increases confidence, repeated evaluation is idempotent and independence/truth are not inferred.
- [x] 6.6 Implement exact contradiction comparability over object, segment, period and metric-definition keys.
- [x] 6.7 Implement the only first-party-not-older-than-benchmark precedence rule and typed reason.
- [x] 6.8 Test missing timestamps, older first-party evidence, equal source classes, ties and uncovered cases as unresolved.
- [x] 6.9 Preserve both contradictory claims and prohibit averaging/deletion.
- [x] 6.10 Exclude unresolved/incomparable claims from accepted IDs while retaining records and typed exclusions.
- [x] 6.11 Derive `FAIL/NO_USABLE_CLAIMS` when none remain, otherwise limited acceptance with a material contradiction limitation.
- [x] 6.12 Test each of object, segment, period and metric-definition mismatch independently plus multiple mismatches as `INCOMPARABLE`.
- [x] 6.13 Add a regression proving selected evidence references resolve and claim membership is validated before comparability, while source class, `observed_at` and precedence rules are not inspected after any comparison-key mismatch produces `INCOMPARABLE`.

## 7. Decisions and synthesis manifest

- [x] 7.1 Implement the complete gate-outcome × decision compatibility matrix after final gate derivation.
- [x] 7.2 Enforce `BLOCKED` gate to matching `BLOCKED` decision and reject stop/replan triggers.
- [x] 7.3 Enforce `FAIL` gate to `STOP/RESULT_FAILED` and reject blocking/replan triggers.
- [x] 7.4 Implement accepted-gate stop precedence while retaining all validated stop/replan triggers.
- [x] 7.5 Implement accepted-gate replan precedence while retaining applicable lower-tier stop triggers.
- [x] 7.6 Implement lower accepted-gate stop precedence, complete reason tuples and deterministic duplicate-trigger rejection.
- [x] 7.7 Build the immutable manifest with propagated limitation source sets, resolved evaluated/accepted IDs, unresolved contradictions and exclusion records.
- [x] 7.8 Test inclusion of eligible accepted results/claims and exclusion of failed, blocked, unresolved and precedence-losing claims.
- [x] 7.9 Prove decisions/manifests generate no plan, prose, raw dump, chain-of-thought or public response DTO.

## 8. Architectural isolation and compatibility

- [x] 8.1 Prove exact zero OpenAI/LLM and `QCService` calls.
- [x] 8.2 Prove zero persistence/context/Job/Redis/queue/worker/workflow calls or transaction ownership.
- [x] 8.3 Prove all five agent result contracts and agent implementations remain unchanged.
- [x] 8.4 Prove presenters and `AgentOutputBuilder` remain unchanged.
- [x] 8.5 Prove public DTOs, routers, APIs and Telegram remain unchanged.
- [x] 8.6 Prove `AgentRegistry` and `TaskPipelineService` remain unchanged.
- [x] 8.7 Prove existing Marketing Orchestrator planner/validator remain independent and every plan remains `PLANNING_ONLY`.

## 9. Verification and evidence

- [x] 9.1 Complete `docs/development/orchestrator-quality-gates-verification.md` with actual focused contract/matrix/propagation/contradiction/decision evidence.
- [x] 9.2 Run focused Quality Gates, Registry, Orchestrator, Expert Core and compatibility tests after remediation.
- [x] 9.3 Run `.venv\Scripts\python.exe -m pytest` and `.venv\Scripts\python.exe -m compileall app bot` after remediation.
- [x] 9.4 Run strict change/all OpenSpec validation and `git diff --check origin/sale-ready...HEAD` after remediation.
- [x] 9.5 Report files, behavior, migrations, exact commands/results, limitations, blockers and manual verification without claiming unexecuted work.

## 10. Closed output-contract implementation evidence

- [x] 10.1 Implement and test exact `BatchId` prefix/type validation.
- [x] 10.2 Implement the exact RFC 8785 tagged-scalar source tree and prove byte/fingerprint stability for equal normalized batches.
- [x] 10.3 Prove fingerprint sensitivity to every caller-owned field with an independently declared matrix and rejection of caller fingerprint injection.
- [x] 10.4 Implement and test every exact propagated `GateDecision` field source set, empty policy, ordering rule and stable identity.
- [x] 10.5 Implement explicit left/right contradiction evidence selection and selected-evidence claim-membership validation.
- [x] 10.6 Prove absent/same selected evidence behavior and zero implicit evidence aggregation, ranking or newest-record selection.
- [x] 10.7 Implement and test complete contradiction-record state coherence and preferred-claim eligibility.
- [x] 10.8 Implement canonical length-prefixed derived limitation preimages and IDs.
- [x] 10.9 Implement canonical length-prefixed derived exclusion preimages and IDs.
- [x] 10.10 Test equal-preimage deduplication, different-preimage collision failure and lexical derived-record ordering.
- [x] 10.11 Implement and test `DecisionRequest` batch ID/fingerprint matching and exact trigger containers.
- [x] 10.12 Implement and test every `DecisionResult` field, identity and matrix-dependent retained reason tuple.
- [x] 10.13 Implement and test the complete batch-identified synthesis manifest, propagated source sets and deep immutability.
- [x] 10.14 Test every exhaustive, non-overlapping exclusion production path.
- [x] 10.15 Prove no unreachable exclusion member or catch-all production path exists.
- [x] 10.16 Prove every derived output, including propagated claim contexts, carries exact batch ID/fingerprint and rejects cross-stage mismatch without object-identity reliance.
- [x] 10.17 Prove outputs generate no user-facing prose, with focused evaluator/manifest assertions.
- [x] 10.18 Prove outputs contain no raw module dump, with the reconciled aggregate field-shape assertions.
- [x] 10.19 Prove outputs expose no hidden chain-of-thought, with reconciled public/internal export inspection.
- [x] 10.20 Prove no universal public DTO is added, with public-schema diff evidence.
- [x] 10.21 Prove zero LLM or `QCService` calls, with isolated call-failure fakes.
- [x] 10.22 Prove zero persistence or workflow calls, with service-boundary isolation fakes.
- [x] 10.23 Prove agents and presenters remain unchanged, with compatibility hashes/tests.
- [x] 10.24 Prove API and Telegram contracts remain unchanged, with router/schema compatibility tests.
- [x] 10.25 Prove `TaskPipelineService` remains unchanged, with focused compatibility tests.
- [x] 10.26 Prove fingerprint sensitivity to every left/right side field and caller-position-preserving side reversal.
- [x] 10.27 Prove side reversal preserves semantic contradiction state/preferred claim while changing batch identity.
- [x] 10.28 Prove `ContradictionRecord` preserves exact validated side values without duplicate flat claim/evidence fields.

## 11. Independent-review remediation (runtime apply paused)

- [x] 11.1 Implement controlled construction for every public caller-owned contract; convert missing, unknown, conflicting and derived/output-only arguments to `QualityGateContractError` while preserving valid positional/keyword construction and immutability.
- [x] 11.2 Preserve every validated stop/replan reason in `DecisionResult` while precedence selects only `decision`; cover all legal tiers, mixed tiers, multiple reasons, duplicates and reordered inputs.
- [x] 11.3 Implement output-only `PropagatedClaimContext` and the exact one-per-claim `BatchEvaluationResult.propagated_claim_contexts` field with batch identity and deep immutability.
- [x] 11.4 Validate an acyclic lineage graph and integrate recursive propagation into `QualityGateEvaluator` before contradiction and final output derivation.
- [x] 11.5 Propagate evidence, assumptions, material limitations and non-material limitations into context, owning `GateDecision` source sets and accepted-result manifest limitations.
- [x] 11.6 Prove multiple-parent/reordered-parent determinism, identical-ID deduplication, unequal-content collision rejection, idempotence, parent failure and conservative effective confidence.
- [x] 11.7 Add independently declared exact-membership tests for every closed Quality Gates enum.
- [x] 11.8 Add adversarial exact-type and nested hostile-value coverage across the complete caller-contract graph, with promised hostile counters remaining zero.
- [x] 11.9 Add an independently declared fingerprint participation matrix for every caller-owned source field, order rule, derived-field exclusion and all four fixed vectors.
- [x] 11.10 Import Registry lookup errors only from the public `app.module_registry` boundary; rerun all focused/full/isolation/compatibility checks and update this task file and verification evidence truthfully.
