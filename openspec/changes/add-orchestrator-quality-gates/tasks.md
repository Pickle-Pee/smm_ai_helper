# Tasks

Authoritative implementation base: `607696ab02da7dafabfcdd0bfeb2f29724b80c38`.

## 1. Completed reconciliation evidence

- [x] 1.1 Verify Registry `1.0.0`, 15 descriptors, zero bindings and normalized checksum `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`.
- [x] 1.2 Verify existing planner/validator, `QCService`, agents, presenters, public DTOs, `AgentRegistry`, `TaskPipelineService` and persistence boundaries.
- [x] 1.3 Reconcile proposal, design, delta spec and product/architecture/governance documents as a planning-only contract.
- [x] 1.4 Create the durable pre-implementation verification template without claiming runtime implementation evidence.

## 2. Package and finite contracts

- [ ] 2.1 Create `app/marketing_orchestrator/quality_gates/` with only the designed internal modules and minimal `__init__.py` exports.
- [ ] 2.2 Implement every canonical enum and prove exact membership and absence of duplicate synonyms.
- [ ] 2.3 Implement normalized caller result/claim/evidence/assumption contracts; prove their field tables and deep freeze independently.
- [ ] 2.4 Implement caller `LimitationRecord`; prove caller ownership and absence of fingerprint cycles.
- [ ] 2.5 Implement `GateDecision`; prove every field source set, empty policy and identity.
- [ ] 2.6 Implement `ContradictionInput`; prove exact selected-evidence fields and membership rules.
- [ ] 2.7 Implement `ContradictionRecord`; prove state-specific tuple coherence and batch association.
- [ ] 2.8 Implement `DerivedLimitationRecord`; prove output-only ownership, references and batch association.
- [ ] 2.9 Implement `ExclusionRecord`; prove subject coherence and all four closed reasons.
- [ ] 2.10 Implement `BatchEvaluationResult`; prove one-to-one nested outputs, ordering and reference resolution.
- [ ] 2.11 Implement `DecisionRequest`; prove exact trigger containers and batch/fingerprint match.
- [ ] 2.12 Implement `DecisionResult`; prove matrix-specific fields and reason emptiness.
- [ ] 2.13 Implement `SynthesisEligibilityManifest`; prove exact source sets and deep freeze.
- [ ] 2.14 Reuse Registry `ModuleId` and `ModuleResultStatus`; add no competing module/status vocabulary.
- [ ] 2.15 Implement immutable caller `ContradictionSide` with complete claim, optional evidence and four typed comparison-key fields; prove no duplicate key vocabulary.

## 3. Exact input and error boundary

- [ ] 3.1 Validate exact scalar types and finite floats used only as claim scalar values; reject bool-as-int ambiguity.
- [ ] 3.2 Validate exact list/tuple/set/frozenset/dict fields before access and defensively freeze accepted containers.
- [ ] 3.3 Reject subclasses and custom Mapping/Sequence/Set values without invoking hostile methods.
- [ ] 3.4 Reject caller-created mapping proxies without inspecting backing mappings; keep internal proxies output-only.
- [ ] 3.5 Validate the prefixed ASCII ID regex, length and field-specific prefix for every ID.
- [ ] 3.6 Validate caller batch/result/claim/evidence/assumption/limitation/contradiction namespaces independently; validate derived exclusion IDs without inventing manifest/decision IDs.
- [ ] 3.7 Resolve all local/cross-result lineage, contradiction, limitation and manifest references after uniqueness validation.
- [ ] 3.8 Normalize caller-caused supported Python/Registry errors to `QualityGateContractError` without catching programmer defects or `BaseException`.
- [ ] 3.9 Add separate hostile-container tests proving validation performs no iteration, lookup, hashing, comparison, formatting, copying, `str()` or `repr()` before type acceptance.
- [ ] 3.10 Add separate exception-boundary tests for `TypeError`, `ValueError`, `KeyError`, `OverflowError`, datetime errors and expected Registry lookup errors.
- [ ] 3.11 Validate left/right side claim resolution, distinct claims, paired evidence presence and evidence membership before comparison.

## 4. Time and Registry validation

- [ ] 4.1 Accept only exact aware `datetime` values, normalize them to UTC preserving microseconds and serialize with `Z`.
- [ ] 4.2 Reject naive/subclass/string timestamps and prove no ambient clock/timezone/filesystem/environment time is read.
- [ ] 4.3 Implement explicit observed-at comparison and `NEWER`/`OLDER`/`SAME`/`UNKNOWN` results.
- [ ] 4.4 Validate canonical registered module identity through injected read-only Registry lookup.
- [ ] 4.5 Validate each supplied declared output name by exact membership in its descriptor without inventing required-output schemas.
- [ ] 4.6 Validate each handoff as a registered target and exact member of the producer descriptor's handoffs.
- [ ] 4.7 Prove Registry remains version `1.0.0`, 15 descriptors and zero execution bindings.

## 5. Legal state and gate outcomes

- [ ] 5.1 Implement the ordered validation phases and deterministic first-error precedence.
- [ ] 5.2 Prove callers cannot supply structural validity, gate outcome, execution readiness or synthesis eligibility.
- [ ] 5.3 Implement and test exact `PASS` derivation, including non-material limitations.
- [ ] 5.4 Implement and test exact `PASS_WITH_LIMITATIONS` derivation and required material limitation.
- [ ] 5.5 Implement and test structurally valid `FAIL` with an empty claim tuple and required typed failure reason.
- [ ] 5.6 Implement and test legitimate `BLOCKED`, `NOT_ASSESSED` and required blocking reason.
- [ ] 5.7 Reject every enumerated illegal status/evidence/limitation/reason/authority/claim combination.
- [ ] 5.8 Reject executable readiness under Registry `1.0.0`; derive `PLANNING_ONLY` only.
- [ ] 5.9 Prove equal evaluation batches yield equal decisions and no side effects.

## 6. Propagation and contradictions

- [ ] 6.1 Implement explicit `ORIGINAL`/`REPEATS`/`REFORMULATES`/`DERIVES` lineage validation.
- [ ] 6.2 Propagate evidence provenance by ID with collision rejection, deduplication and stable ordering.
- [ ] 6.3 Propagate assumptions and material/non-material limitations without type conversion or loss.
- [ ] 6.4 Enforce `UNKNOWN < LOW < MEDIUM < HIGH`, parent ceilings and multi-parent minimum confidence.
- [ ] 6.5 Prove new evidence never increases confidence and independence/truth are not inferred.
- [ ] 6.6 Implement exact contradiction comparability over object, segment, period and metric-definition keys.
- [ ] 6.7 Implement the only first-party-not-older-than-benchmark precedence rule and typed reason.
- [ ] 6.8 Test missing timestamps, older first-party evidence, equal source classes, ties and uncovered cases as unresolved.
- [ ] 6.9 Preserve both contradictory claims and prohibit averaging/deletion.
- [ ] 6.10 Exclude unresolved/incomparable claims from accepted IDs while retaining records and typed exclusions.
- [ ] 6.11 Derive `FAIL/NO_USABLE_CLAIMS` when none remain, otherwise limited acceptance with a material contradiction limitation.
- [ ] 6.12 Test each of object, segment, period and metric-definition mismatch independently plus multiple mismatches as `INCOMPARABLE`.
- [ ] 6.13 Add a regression proving selected evidence references resolve and claim membership is validated before comparability, while source class, `observed_at` and precedence rules are not inspected after any comparison-key mismatch produces `INCOMPARABLE`.

## 7. Decisions and synthesis manifest

- [ ] 7.1 Implement the complete gate-outcome × decision compatibility matrix after final gate derivation.
- [ ] 7.2 Enforce `BLOCKED` gate to matching `BLOCKED` decision and reject stop/replan triggers.
- [ ] 7.3 Enforce `FAIL` gate to `STOP/RESULT_FAILED` and reject blocking/replan triggers.
- [ ] 7.4 Implement accepted-gate stop precedence for scope-complete and sufficient-evidence triggers.
- [ ] 7.5 Implement accepted-gate replan precedence for material finding, invalidated dependency and reversible-test value.
- [ ] 7.6 Implement lower accepted-gate stop precedence for diminishing/tool/capability limits and deterministic duplicate-trigger rejection.
- [ ] 7.7 Build the immutable manifest with resolved evaluated/accepted IDs, unresolved contradictions, limitations and exclusion records.
- [ ] 7.8 Test inclusion of eligible accepted results/claims and exclusion of failed, blocked, unresolved and precedence-losing claims.
- [ ] 7.9 Prove decisions/manifests generate no plan, prose, raw dump, chain-of-thought or public response DTO.

## 8. Architectural isolation and compatibility

- [ ] 8.1 Prove exact zero OpenAI/LLM and `QCService` calls.
- [ ] 8.2 Prove zero persistence/context/Job/Redis/queue/worker/workflow calls or transaction ownership.
- [ ] 8.3 Prove all five agent result contracts and agent implementations remain unchanged.
- [ ] 8.4 Prove presenters and `AgentOutputBuilder` remain unchanged.
- [ ] 8.5 Prove public DTOs, routers, APIs and Telegram remain unchanged.
- [ ] 8.6 Prove `AgentRegistry` and `TaskPipelineService` remain unchanged.
- [ ] 8.7 Prove existing Marketing Orchestrator planner/validator remain independent and every plan remains `PLANNING_ONLY`.

## 9. Verification and evidence

- [ ] 9.1 Complete `docs/development/orchestrator-quality-gates-verification.md` with actual focused contract/matrix/propagation/contradiction/decision evidence.
- [ ] 9.2 Run focused Quality Gates, Registry, Orchestrator, Expert Core and compatibility tests.
- [ ] 9.3 Run `.venv\Scripts\python.exe -m pytest` and `.venv\Scripts\python.exe -m compileall app bot`.
- [ ] 9.4 Run strict change/all OpenSpec validation and `git diff --check origin/sale-ready...HEAD`.
- [ ] 9.5 Report files, behavior, migrations, exact commands/results, limitations, blockers and manual verification without claiming unexecuted work.

## 10. Closed output-contract implementation evidence

- [ ] 10.1 Implement and test exact `BatchId` prefix/type validation.
- [ ] 10.2 Implement the exact RFC 8785 tagged-scalar source tree and prove byte/fingerprint stability for equal normalized batches.
- [ ] 10.3 Prove fingerprint sensitivity to every contract-relevant field and rejection of caller fingerprint injection.
- [ ] 10.4 Implement and test every exact `GateDecision` field, empty policy, ordering rule and stable identity.
- [ ] 10.5 Implement explicit left/right contradiction evidence selection and selected-evidence claim-membership validation.
- [ ] 10.6 Prove absent/same selected evidence behavior and zero implicit evidence aggregation, ranking or newest-record selection.
- [ ] 10.7 Implement and test complete contradiction-record state coherence and preferred-claim eligibility.
- [ ] 10.8 Implement canonical length-prefixed derived limitation preimages and IDs.
- [ ] 10.9 Implement canonical length-prefixed derived exclusion preimages and IDs.
- [ ] 10.10 Test equal-preimage deduplication, different-preimage collision failure and lexical derived-record ordering.
- [ ] 10.11 Implement and test `DecisionRequest` batch ID/fingerprint matching and exact trigger containers.
- [ ] 10.12 Implement and test every `DecisionResult` field, identity and matrix-dependent empty tuple.
- [ ] 10.13 Implement and test the complete batch-identified synthesis manifest and deep immutability.
- [ ] 10.14 Test every exhaustive, non-overlapping exclusion production path.
- [ ] 10.15 Prove no unreachable exclusion member or catch-all production path exists.
- [ ] 10.16 Prove every derived output carries exact batch ID/fingerprint and rejects cross-stage mismatch without object-identity reliance.
- [ ] 10.17 Prove outputs generate no user-facing prose, with focused evaluator/manifest assertions.
- [ ] 10.18 Prove outputs contain no raw module dump, with aggregate field-shape assertions.
- [ ] 10.19 Prove outputs expose no hidden chain-of-thought, with public/internal export inspection.
- [ ] 10.20 Prove no universal public DTO is added, with public-schema diff evidence.
- [ ] 10.21 Prove zero LLM or `QCService` calls, with isolated call-failure fakes.
- [ ] 10.22 Prove zero persistence or workflow calls, with service-boundary isolation fakes.
- [ ] 10.23 Prove agents and presenters remain unchanged, with compatibility hashes/tests.
- [ ] 10.24 Prove API and Telegram contracts remain unchanged, with router/schema compatibility tests.
- [ ] 10.25 Prove `TaskPipelineService` remains unchanged, with focused compatibility tests.
- [ ] 10.26 Prove fingerprint sensitivity to every left/right side field and caller-position-preserving side reversal.
- [ ] 10.27 Prove side reversal preserves semantic contradiction state/preferred claim while changing batch identity.
- [ ] 10.28 Prove `ContradictionRecord` preserves exact validated side values without duplicate flat claim/evidence fields.
