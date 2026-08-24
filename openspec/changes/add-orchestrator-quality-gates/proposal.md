## Why

The planning-only Marketing Orchestrator needs an exact deterministic boundary for deciding whether caller-supplied typed module results can safely participate in later decision support. Without this contract, runtime implementation would have to invent identity, confidence, state, contradiction and propagation semantics.

## What Changes

- Add a private `app/marketing_orchestrator/quality_gates/` package for immutable normalized-result contracts and pure evaluation.
- Define every finite vocabulary, dataclass field, batch identity/fingerprint, ID namespace, timestamp rule and error phase.
- Separate caller limitations from batch-associated derived limitations, expose a complete batch evaluation aggregate, and require byte-exact RFC 8785 fingerprints.
- Require immutable caller-supplied left/right contradiction sides with complete typed scope keys and caller-selected evidence; derive comparability before evidence precedence, with deterministic limitation/exclusion identities and no catch-all states.
- Derive gate outcomes, execution readiness, decisions and synthesis eligibility rather than trusting caller-supplied values.
- Preserve provenance, assumptions, material/non-material limitations and explicit lineage through an output-only per-claim propagated context, with conservative confidence propagation reflected in the aggregate, gate decisions and manifest source sets.
- Close every public caller-owned constructor behind `QualityGateContractError`, and preserve every validated decision trigger while precedence selects only the final decision.
- Add exact contradiction, stop/replan and synthesis-manifest rules.
- Add independently verifiable negative, adversarial, isolation and compatibility tasks.

## Capabilities

### New Capabilities

- `orchestrator-quality-gates`: Pure structural evaluation and downstream-eligibility decisions for immutable normalized module results.

### Modified Capabilities

None.

## Impact

- Planned code ownership is limited to `app/marketing_orchestrator/quality_gates/` and focused tests.
- Quality Gates may use public Module Registry types and read-only lookup; Registry `1.0.0` remains 15 metadata-only descriptors with zero execution bindings.
- Existing planner/validator, agents, presenters, public DTOs, `AgentRegistry`, `QCService` and `TaskPipelineService` remain unchanged and do not depend on Quality Gates.
- No API, Telegram, persistence, transaction, migration, Job, Redis, queue, worker, workflow execution, prompt, LLM/QC call or user-facing synthesis is introduced.
- Existing agent dictionaries require future explicit adapters and are not accepted directly.
- Authoritative implementation base: `607696ab02da7dafabfcdd0bfeb2f29724b80c38`.
