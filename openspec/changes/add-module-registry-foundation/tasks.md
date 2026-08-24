## 1. Domain and resource setup

- [x] 1.1 Add the app-owned package and canonical `app/module_registry/v1.0.0.json` with source version `1.0.0` and exactly fifteen expected descriptors.
- [x] 1.2 Add immutable descriptor, module-type, input-requirement, tool-capability, availability-status, result-status, activation, return, and optional execution-binding types without changing public DTOs.
- [x] 1.3 Keep descriptor data exclusively in JSON; Python contains only schemas, fixed validation expectations, loading, validation, and lookup.

## 2. Read-only registry and validation

- [x] 2.1 Implement a read-only provider that loads versioned app data and returns immutable descriptors without invoking execution services.
- [x] 2.2 Implement the specified whitespace/case/hyphen/underscore normalization and collision-checked canonical lookup.
- [x] 2.3 Fail fast on duplicate/missing/unexpected IDs, invalid counts, empty fields, invalid enums, unsupported tools, invalid/self handoffs, alias collisions/ambiguity, invalid source version, and mutation attempts.
- [x] 2.4 Validate optional binding targets against `AgentRegistry`, require exact compatibility, reject inconsistent availability/binding state, and declare zero v1.0.0 bindings.
- [x] 2.5 Do not inject or consume `ModuleRegistry` in `TaskRouter`, `AgentRunner`, or `TaskPipelineService`.

## 3. Deterministic tests

- [x] 3.1 Test exactly fifteen expected IDs, one descriptor per ID, immutable lookup, and source version.
- [x] 3.2 Test alias normalization/resolution and duplicate, canonical-collision, ambiguous, and empty failures.
- [x] 3.3 Test fields, enums, capabilities, handoff targets, and prohibited self-handoffs.
- [x] 3.4 Test zero v1.0.0 bindings and rejection of unknown targets or inconsistent binding state.
- [x] 3.5 Add regressions proving the five existing agent mappings and router, runner, pipeline, public result, LLM-call, and QC-call behavior remain unchanged.

## 4. Import verification and documentation

- [x] 4.1 Compare every imported descriptor against approved source material for IDs, aliases, inputs, outputs, tools, gates, handoffs, authority limits, availability/binding state, and source version.
- [x] 4.2 Record normalized JSON SHA-256 and completed evidence in `docs/development/module-registry-verification.md` without copying descriptors.
- [x] 4.3 Update governance documentation only if implementation changes the planned path/procedure; never create another canonical descriptor source.

## 5. Verification

- [x] 5.1 Run focused registry and compatibility tests without real OpenAI calls.
- [x] 5.2 Run `python -m compileall app bot`.
- [x] 5.3 Run `python -m pytest` (executed: 149 passed, 1 confirmed baseline Expert Core failure; see verification document).
- [x] 5.4 Run both strict change and all-change OpenSpec validation commands.
- [x] 5.5 Confirm and report no public API, database/Alembic, Redis, worker, workflow, Telegram, added LLM/QC, or routing/execution changes.
