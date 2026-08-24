# Change: Add deterministic orchestrator quality gates

## Why

The planning-only Marketing Orchestrator can create validated plans, but no typed boundary yet determines whether caller-supplied module results are structurally safe for downstream decision support. A deterministic foundation is needed to preserve provenance, assumptions, confidence, limitations and contradictions without pretending to verify marketing truth.

## What changes

- Add one deeply immutable normalized-result contract for already-typed, caller-supplied results.
- Add exact-type construction validation and a dedicated contract-error boundary.
- Keep module-declared status, structural validity, gate outcome, evidence sufficiency, confidence, limitations, contradiction state, next-step decision, stop decision, execution readiness and synthesis eligibility separate.
- Add a deterministic legal-state matrix for `PASS`, `PASS_WITH_LIMITATIONS`, `FAIL` and `BLOCKED` gate outcomes.
- Preserve claim/evidence identity, provenance, assumptions and material limitations through pure propagation helpers.
- Represent contradictions, replanning triggers, stop triggers and synthesis eligibility as typed data.
- Validate registered module and handoff identities against Module Registry `1.0.0` metadata.
- Document isolation and add deterministic, adversarial tests.

## Runtime compatibility

- `QCService` remains unchanged because it is an existing model-based editorial check; Quality Gates make no LLM or QC call and add no second QC pass.
- Existing agents, their heterogeneous result dictionaries, `AgentOutputBuilder`, presenters and public response DTOs remain unchanged. Future adapters may normalize compatible results explicitly.
- `TaskPipelineService` remains the single-task pipeline and is not connected to this foundation.
- Module Registry `1.0.0` remains metadata-only with 15 descriptors and zero execution bindings. Its metadata can validate identities, declared output names and registered handoffs, but cannot prove module-specific output completeness or semantic authority.
- Every Marketing Orchestrator plan remains `PLANNING_ONLY`.
- Quality Gates own no transaction because evaluation is pure and non-persistent.

## Dependencies

- Expert Core foundation.
- Module Registry `1.0.0` foundation.
- Marketing Orchestrator planning foundation.
- Authoritative reconciliation base: `607696ab02da7dafabfcdd0bfeb2f29724b80c38`.

## Out of scope

- Module or agent execution and executable Registry bindings.
- LLM calls, `QCService` calls, semantic truth/causality/strategy evaluation, prose contradiction discovery, or evidence-independence inference.
- Natural-language request parsing, context/persistence queries, writes, transactions, migrations, Jobs, Redis, queues or workers.
- Workflow execution, revised-plan generation/execution, public APIs or Telegram integration.
- User-facing synthesis, raw module dumps, hidden chain-of-thought, a universal response wrapper, or presenter replacement.
- Adapters from current agent-specific dictionaries and module-specific normalized schemas.

