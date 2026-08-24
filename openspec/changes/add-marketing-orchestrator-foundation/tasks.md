# Tasks

## 1. Internal contracts

- [x] 1.1 Add deeply immutable `RequestInterpretation`, tagged `PlanningContext`/facts and validation; accept only an explicit module/alias or supported scenario key, never arbitrary free-text inference.
- [x] 1.2 Add immutable plan, node, graph-dependency, input-requirement and context-packet contracts with separate structural validity, data sufficiency, planning status and execution readiness.
- [x] 1.3 Derive stable plan identity from canonical input/context identities, Registry version/checksum and scenario; use stable node IDs and no random IDs.
- [x] 1.4 Keep all contracts internal with no public DTO, API, Telegram, database or migration changes.

## 2. Deterministic planner

- [x] 2.1 Implement the read-only Registry-backed planner lifecycle: `INTERPRET -> CHECK_CONTEXT -> CHECK_EVIDENCE -> PLAN -> VALIDATE_PLAN -> RETURN_PLAN_OR_BLOCK`.
- [x] 2.2 Implement only `explicit_single_module_v1` and `new_positioning_v1`; reject every other scenario without guessing.
- [x] 2.3 Resolve aliases before return and store only canonical module IDs.
- [x] 2.4 Build deterministic node, edge, topological and blocking-question order.
- [x] 2.5 Scope tagged authorized context per node; exclude unrelated facts/secrets, include upstream findings only for dependent nodes and do not query context/persistence services.
- [x] 2.6 Check known inputs before questions; cap unique decision-changing blocking questions at three; turn missing preferred/optional inputs into limitations.
- [x] 2.7 Return `PLANNING_ONLY` execution readiness for Registry `1.0.0`; add no execution binding.

## 3. Validation

- [x] 3.1 Validate unique nodes, canonical registered modules, resolved aliases, existing dependency targets, no self-edge/cycle and deterministic topology.
- [x] 3.2 Validate parallel metadata against direct/transitive dependencies.
- [x] 3.3 Validate expected-output and quality-gate selections against Registry descriptors.
- [x] 3.4 Validate explicit input classification without overloading graph dependency types.
- [x] 3.5 Implement exact planning stop results: `PLAN_COMPLETE`, `BLOCKING_INPUT_MISSING`, `UNKNOWN_MODULE`, `UNSUPPORTED_SCENARIO`, `INVALID_PLAN`.

## 4. Independent tests (no external services)

- [x] 4.1 Exact supported scenario catalog and explicit single-module plan.
- [x] 4.2 Canonical alias resolution and unknown-module rejection.
- [x] 4.3 `new_positioning_v1` graph, parallel upstream nodes and sequential downstream node.
- [x] 4.4 Deterministic node, dependency, topology, plan identity and question order.
- [x] 4.5 Unsupported scenario and missing dependency rejection.
- [x] 4.6 Cycle, self-dependency and invalid parallel metadata rejection.
- [x] 4.7 Expected-output and quality-gate descriptor mismatch rejection.
- [x] 4.8 Maximum three unique blocking questions, no duplicates and no question for known context.
- [x] 4.9 Missing optional/preferred input produces a limitation, not a blocker.
- [x] 4.10 Scoped node context, unrelated-context exclusion and upstream findings only on dependent nodes.
- [x] 4.11 Structurally valid plan reports `PLANNING_ONLY` execution readiness.
- [x] 4.12 Spies/fakes prove zero agent, model, QC, database, Redis, worker, module-execution and persistence calls.
- [x] 4.13 Regression tests prove existing single-task routing and `TaskPipelineService` behavior is unchanged.

## 5. Documentation and verification

- [x] 5.1 Update `ARCHITECTURE.md` only after implementation exists, describing the actual internal planning boundary without an execution path.
- [x] 5.2 Complete `docs/development/marketing-orchestrator-verification.md` with actual supported catalog, Registry version/checksum, deterministic examples, context evidence, coverage, readiness and compatibility results.
- [x] 5.3 Run `.venv\Scripts\python.exe -m pytest`.
- [x] 5.4 Run `.venv\Scripts\python.exe -m compileall app bot`.
- [x] 5.5 Run `openspec validate add-marketing-orchestrator-foundation --strict` and `openspec validate --all --strict`.
- [x] 5.6 Run `git diff --check` and report exact commands, limitations, and no API/database/migration impact.

## Explicit exclusions

Do not add API/Telegram integration, a dispatcher, changes to `TaskRouter`/`AgentRunner`/`TaskPipelineService`, Registry bindings, module implementations, execution, workflow persistence, Jobs, queues, Redis, workers, LLM calls/prompts, QC, runtime replanning, synthesis, delivery, learning or unrelated refactoring.

## 6. Review hardening

- [x] 6.1 Validate the exact independently declared positioning node/module/edge topology, dependency references, parallel membership, and deterministic ordering.
- [x] 6.2 Enforce global planning-only, zero-binding, question and plan-state matrix invariants before every scenario-specific return.
- [x] 6.3 Replace Registry-prose-derived questions with explicit typed input keys, priorities, applicability and deterministic templates.
- [x] 6.4 Derive plan identity only from canonical interpretation, selected graph and authorized relevant context that survives node scoping.
- [x] 6.5 Enforce a recursively immutable canonical JSON-like value contract and reject mutable or non-deterministic values.
- [x] 6.6 Add independent regressions for every review finding and rerun targeted, compatibility, full, OpenSpec, compilation and diff checks.

## 7. Typed context boundary hardening

- [x] 7.1 Separate stable unique `fact_id`, human-only `label`, and optional exact-enum `input_key`; remove prose normalization from requirement matching.
- [x] 7.2 Derive scoped plan identity from stable fact identity and frozen value while excluding labels, source text, unscoped facts, and caller ordering.
- [x] 7.3 Validate and defensively freeze the complete planning contract graph at construction with `InvalidContextValueError`.
- [x] 7.4 Add independent regressions for prose-like keys, raw enum strings, duplicate identities, metadata validation, and caller mutation.

## 8. Exact container boundary hardening

- [x] 8.1 Accept only exact approved built-in container and scalar types before iteration, and reject subclasses/custom containers with `InvalidContextValueError`.
- [x] 8.2 Make fact source truthfully optional (`None` means unspecified), while rejecting empty or non-exact strings and keeping source out of matching and identity.
- [x] 8.3 Add adversarial subclass regressions proving overridden methods are not invoked and normal built-ins remain defensively frozen.
- [x] 8.4 Rerun targeted, compatibility, full, OpenSpec, compilation, and scope checks and record exact results; confirm required PR CI after push.

## 9. Proxy trust and transition closure

- [x] 9.1 Reject every caller-supplied mapping proxy before access while retaining mapping proxies only as immutable outputs of validated exact dictionaries.
- [x] 9.2 Validate the independently declared exact `next_if_pass`/`next_if_fail` table for every `new_positioning_v1` node.
- [x] 9.3 Add hostile wrapped-mapping and exhaustive malformed-transition regressions with independent expectations.
- [x] 9.4 Rerun targeted, compatibility, full, OpenSpec, compilation, and scope checks and record exact results; confirm required PR CI after push.
