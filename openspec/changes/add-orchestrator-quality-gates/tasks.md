# Tasks

Authoritative implementation base: `607696ab02da7dafabfcdd0bfeb2f29724b80c38`.

All tasks below are intentionally incomplete during pre-implementation reconciliation.

## 1. Contracts and exact validation

- [ ] 1.1 Add a dedicated `QualityGateContractError` boundary and frozen, slotted normalized-result contracts with stable result, claim, evidence, assumption and limitation IDs.
- [ ] 1.2 Enforce exact accepted scalar/container types, finite numeric confidence, canonical IDs, defensive copying and deep immutability; reject subclasses, custom collections, mutable `Any`, duplicate IDs and dangling references.
- [ ] 1.3 Keep module status, structural validity, gate outcome, evidence sufficiency, confidence, limitation materiality, contradiction state, next-step decision, stop decision, execution readiness and synthesis eligibility as distinct types.
- [ ] 1.4 Validate canonical module identity, declared Registry output membership where supplied and registered handoffs against injected Module Registry `1.0.0`; do not invent module-specific required schemas.

## 2. Deterministic gate evaluation

- [ ] 2.1 Implement the complete legal-state matrix for `PASS`, `PASS_WITH_LIMITATIONS`, `FAIL` and `BLOCKED` and reject every contradictory combination as a contract error.
- [ ] 2.2 Distinguish malformed input from a valid blocked result and from a structurally valid explicit unusable failure.
- [ ] 2.3 Return immutable deterministic gate decisions with no side effects and prove evaluation idempotency.
- [ ] 2.4 Preserve `PLANNING_ONLY`; add no Registry execution binding, module execution, dispatcher or workflow behavior.

## 3. Propagation and contradictions

- [ ] 3.1 Implement deterministic, order-independent identity-based evidence/claim propagation that never drops provenance or changes an assumption into a fact.
- [ ] 3.2 Preserve every material limitation downstream and reject unequal records that reuse a stable ID.
- [ ] 3.3 Enforce conservative confidence: repetition/reformulation never raises confidence, new evidence is retained but cannot raise confidence in this foundation, and derived confidence cannot exceed required sources.
- [ ] 3.4 Add typed contradiction records with object, segment, period, metric definition, provenance/source class, freshness, compared claim IDs, resolution state and optional precedence reason.
- [ ] 3.5 Implement exact first-party/current versus generic-benchmark precedence, unresolved/incomparable/tie behavior, preservation of both claims and prohibition on averaging.

## 4. Replanning, stopping and synthesis eligibility

- [ ] 4.1 Add typed explicit triggers and pure decisions for `CONTINUE_CURRENT_PLAN`, `REPLAN_REQUIRED`, `STOP` and `BLOCKED` with documented precedence.
- [ ] 4.2 Distinguish successful completion, blocked input, failed module result, sufficient evidence, diminishing value, unavailable capability, reversible-test preference and future replanning requirement.
- [ ] 4.3 Keep prior plans/findings immutable; request but do not create or execute a revised plan and invoke no module for completeness.
- [ ] 4.4 Add the optional deterministic synthesis-eligibility manifest containing accepted result/claim IDs, material limitations, unresolved contradictions and typed exclusions only.
- [ ] 4.5 Generate no user-facing prose, response wrapper, raw module dump, routing trace or hidden chain-of-thought; do not modify presenters.

## 5. Compatibility and adversarial tests

- [ ] 5.1 Cover every legal and illegal state combination, missing fields, exact-type/subclass attacks, hostile containers, duplicate/dangling IDs, non-finite values and caller-mutation attempts.
- [ ] 5.2 Cover known/unknown modules, legal/illegal handoffs and Registry `1.0.0` zero-binding invariants.
- [ ] 5.3 Cover provenance preservation, assumption/limitation propagation, identity collisions, deterministic ordering and conservative confidence.
- [ ] 5.4 Cover contradiction comparability, explicit precedence, missing freshness, ties, unresolved state and no averaging/deletion.
- [ ] 5.5 Cover decision-trigger precedence, stop reasons, idempotency and synthesis-manifest inclusion/exclusion.
- [ ] 5.6 Prove zero LLM, `QCService`, agent, persistence/context, Job, Redis, queue, worker, API and Telegram calls.
- [ ] 5.7 Prove existing agents, heterogeneous result dictionaries, presenters, public DTOs, `AgentRegistry`, `TaskPipelineService`, Module Registry and Marketing Orchestrator behavior remain unchanged.

## 6. Documentation and verification

- [ ] 6.1 Update architecture/product documentation and complete `docs/development/orchestrator-quality-gates-verification.md` with actual implementation evidence.
- [ ] 6.2 Run focused Quality Gates, Marketing Orchestrator, Module Registry, Expert Core and compatibility tests.
- [ ] 6.3 Run `.venv\Scripts\python.exe -m pytest` and `.venv\Scripts\python.exe -m compileall app bot`.
- [ ] 6.4 Run `openspec validate add-orchestrator-quality-gates --strict`, `openspec validate --all --strict` and `git diff --check origin/sale-ready...HEAD`.
- [ ] 6.5 Report actual files, behavior, migrations, commands, passed checks, limitations, blockers and manual verification; do not claim unexecuted work.

