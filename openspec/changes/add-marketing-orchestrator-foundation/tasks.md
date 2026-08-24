# Tasks

## 1. Internal contracts

- [ ] 1.1 Add deeply immutable `RequestInterpretation`, tagged `PlanningContext`/facts and validation; accept only an explicit module/alias or supported scenario key, never arbitrary free-text inference.
- [ ] 1.2 Add immutable plan, node, graph-dependency, input-requirement and context-packet contracts with separate structural validity, data sufficiency, planning status and execution readiness.
- [ ] 1.3 Derive stable plan identity from canonical input/context identities, Registry version/checksum and scenario; use stable node IDs and no random IDs.
- [ ] 1.4 Keep all contracts internal with no public DTO, API, Telegram, database or migration changes.

## 2. Deterministic planner

- [ ] 2.1 Implement the read-only Registry-backed planner lifecycle: `INTERPRET -> CHECK_CONTEXT -> CHECK_EVIDENCE -> PLAN -> VALIDATE_PLAN -> RETURN_PLAN_OR_BLOCK`.
- [ ] 2.2 Implement only `explicit_single_module_v1` and `new_positioning_v1`; reject every other scenario without guessing.
- [ ] 2.3 Resolve aliases before return and store only canonical module IDs.
- [ ] 2.4 Build deterministic node, edge, topological and blocking-question order.
- [ ] 2.5 Scope tagged authorized context per node; exclude unrelated facts/secrets, include upstream findings only for dependent nodes and do not query context/persistence services.
- [ ] 2.6 Check known inputs before questions; cap unique decision-changing blocking questions at three; turn missing preferred/optional inputs into limitations.
- [ ] 2.7 Return `PLANNING_ONLY` execution readiness for Registry `1.0.0`; add no execution binding.

## 3. Validation

- [ ] 3.1 Validate unique nodes, canonical registered modules, resolved aliases, existing dependency targets, no self-edge/cycle and deterministic topology.
- [ ] 3.2 Validate parallel metadata against direct/transitive dependencies.
- [ ] 3.3 Validate expected-output and quality-gate selections against Registry descriptors.
- [ ] 3.4 Validate explicit input classification without overloading graph dependency types.
- [ ] 3.5 Implement exact planning stop results: `PLAN_COMPLETE`, `BLOCKING_INPUT_MISSING`, `UNKNOWN_MODULE`, `UNSUPPORTED_SCENARIO`, `INVALID_PLAN`.

## 4. Independent tests (no external services)

- [ ] 4.1 Exact supported scenario catalog and explicit single-module plan.
- [ ] 4.2 Canonical alias resolution and unknown-module rejection.
- [ ] 4.3 `new_positioning_v1` graph, parallel upstream nodes and sequential downstream node.
- [ ] 4.4 Deterministic node, dependency, topology, plan identity and question order.
- [ ] 4.5 Unsupported scenario and missing dependency rejection.
- [ ] 4.6 Cycle, self-dependency and invalid parallel metadata rejection.
- [ ] 4.7 Expected-output and quality-gate descriptor mismatch rejection.
- [ ] 4.8 Maximum three unique blocking questions, no duplicates and no question for known context.
- [ ] 4.9 Missing optional/preferred input produces a limitation, not a blocker.
- [ ] 4.10 Scoped node context, unrelated-context exclusion and upstream findings only on dependent nodes.
- [ ] 4.11 Structurally valid plan reports `PLANNING_ONLY` execution readiness.
- [ ] 4.12 Spies/fakes prove zero agent, model, QC, database, Redis, worker, module-execution and persistence calls.
- [ ] 4.13 Regression tests prove existing single-task routing and `TaskPipelineService` behavior is unchanged.

## 5. Documentation and verification

- [ ] 5.1 Update `ARCHITECTURE.md` only after implementation exists, describing the actual internal planning boundary without an execution path.
- [ ] 5.2 Complete `docs/development/marketing-orchestrator-verification.md` with actual supported catalog, Registry version/checksum, deterministic examples, context evidence, coverage, readiness and compatibility results.
- [ ] 5.3 Run `.venv\Scripts\python.exe -m pytest`.
- [ ] 5.4 Run `.venv\Scripts\python.exe -m compileall app bot`.
- [ ] 5.5 Run `openspec validate add-marketing-orchestrator-foundation --strict` and `openspec validate --all --strict`.
- [ ] 5.6 Run `git diff --check` and report exact commands, limitations, and no API/database/migration impact.

## Explicit exclusions

Do not add API/Telegram integration, a dispatcher, changes to `TaskRouter`/`AgentRunner`/`TaskPipelineService`, Registry bindings, module implementations, execution, workflow persistence, Jobs, queues, Redis, workers, LLM calls/prompts, QC, runtime replanning, synthesis, delivery, learning or unrelated refactoring.
