# Marketing Orchestrator foundation verification

## Identification

- Branch: `agent/fix-marketing-orchestrator-foundation`
- Base `origin/sale-ready`: `534f98d37a2e2f4c74953383a0ea515a38ab76bb`
- Restored source commits: `125bb63269e0094eecfa1210b6105c05fd2b3bec`, `4252ad9161b67ceb0ab938cb3b4d6bf16f48210f`
- Recovery: both source commits were cherry-picked in order onto the clean `sale-ready` base; no merge commit or `master` history is present.
- Contracts/planner/validator: `app/marketing_orchestrator/`
- Tests: `tests/test_marketing_orchestrator.py`

## Module Registry dependency

- Version: `1.0.0`
- Normalized SHA-256: `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`
- Descriptors: 15 metadata-only modules
- Execution bindings: 0

The planner receives the read-only Registry through a narrow constructor dependency. Aliases resolve through Registry lookup; returned nodes contain canonical `ModuleId` values only.

## Exact scenarios and graphs

1. `explicit_single_module_v1`: one registered canonical module or approved alias, no edges.
2. `new_positioning_v1`: exactly:

```text
market_analysis       (MARKET_ANALYSIS) ------+
                                               +--> positioning (POSITIONING)
competitor_analysis   (COMPETITOR_ANALYSIS) --+
```

Node order is `market_analysis`, `competitor_analysis`, `positioning`. Edge order is `competitor_analysis -> positioning`, then `market_analysis -> positioning`. Validation compares independently declared exact node IDs, module mapping, edge set, node dependency references and parallel membership. Equivalent effective scoped inputs reproduce the same deterministic SHA-256 plan ID.

## Context, questions, and validation evidence

Tests prove only authorized module/scenario-tagged facts enter packets; unrelated and unauthorized secret facts are excluded; independent nodes receive no upstream findings; positioning receives findings only from its declared dependencies; known inputs suppress questions; missing blocking keys are deduplicated and capped at three; and preferred/optional gaps become limitations.

Question generation uses only immutable `PlanningInputRequirement` entries with stable `PlanningInputKey`, classification, priority, scenario/module applicability and approved templates. Authorized facts separate a validated stable `fact_id`, human-only `label`, and optional exact-enum `input_key`. Exact enum equality is the only match: tests prove `label="Product or category"` with no key remains blocking and both `"Product or category"` and `"product_or_category"` raw input-key strings fail construction. Registry prose is never converted into keys.

Plan identity is constructed after authorization and node scoping. It includes stable fact IDs and canonical frozen values, but excludes labels and free-form sources. Reordering facts produces the same ID; unrelated `CREATOR` facts and unauthorized facts alter neither packets nor ID; changing or removing an effective relevant identity/value changes the ID. Duplicate `fact_id` values fail at `PlanningContext` construction.

Every planning dataclass validates at construction through the shared `InvalidContextValueError` boundary. Fact and upstream-finding values accept only recursive canonical JSON-like values. Lists and string-keyed mappings are copied into tuples and immutable deterministic mappings. Metadata tests reject mutable/non-string source and evidence, bare-string or byte-array sequences, unsupported enum strings, booleans/non-finite/out-of-range confidence, sets, custom mutable objects and non-string mapping keys. Caller list/dictionary mutation cannot affect constructed contracts.

Malformed fixtures independently cover each missing positioning edge, both edges missing, extra edges, edge/reference disagreement in both directions, wrong deterministic IDs, incorrect topology with the correct module sequence, duplicate IDs, unresolved/unknown modules, missing targets, self-edges, cycles, invalid parallel groups, output/gate mismatches, duplicate/excess/known-input questions, and unsupported graphs.

The explicit state matrix accepts only validated sufficient/partial plans, blocked insufficient plans with one to three questions, and empty unsupported results with the approved stop. Global invariants run before scenario early returns, so executable unsupported results, blocked plans without questions, ready plans with questions, partial plans without limitations, and contradictory status/sufficiency/stop combinations raise `InvalidPlanError`.

## Readiness and isolation

- Structural validity, data sufficiency, planning status, and execution readiness are separate.
- Every valid plan is `PLANNING_ONLY`.
- Tests/source isolation show zero agent, model, prompt, QC, database-session, workflow-persistence, Redis, queue, worker, module-execution, or external-service calls.
- Existing `AgentRegistry`, public DTOs, routers, `TaskRouter`, `AgentRunner`, and `TaskPipelineService` are unchanged.
- No product Orchestrator prompt is read and no `app/prompts/orchestrator` exists.

## Commands and results

| Command | Exit | Result |
| --- | ---: | --- |
| `.venv\Scripts\python.exe -m pytest tests/test_marketing_orchestrator.py -q` | 0 | 83 passed, 4 existing deprecation warnings |
| `.venv\Scripts\python.exe -m pytest -q tests\test_marketing_orchestrator.py tests\test_module_registry.py tests\test_expert_core.py tests\test_agent_registry.py tests\test_task_router.py tests\test_task_pipeline_service.py tests\test_marketing_workflow_persistence_service.py --tb=short` | 0 | 156 passed, 6 existing deprecation warnings |
| `.venv\Scripts\python.exe -m pytest -q` | 0 | 235 passed, 9 existing deprecation warnings |
| `.venv\Scripts\python.exe -m compileall app bot` | 0 | compiled successfully |
| `openspec validate add-marketing-orchestrator-foundation --strict` | 0 | valid |
| `openspec validate --all --strict` | 0 | 11 passed, 0 failed |
| `git diff --check origin/sale-ready...HEAD` | 0 | no whitespace errors |

Warnings are existing Pydantic class-config and naive `datetime.utcnow()` deprecations; this change does not modify those areas.

## Impact and limitations

- API/Telegram/database/model/migration impact: none; no Alembic migration.
- Routing/pipeline compatibility: unchanged; compatibility tests pass.
- LLM/QC/persistence/Redis/queue/worker impact: none.
- Calls made by the foundation: zero LLM, QC, database, Redis, worker, workflow, persistence, module-execution or external-service calls.
- Planning is limited to the exact two scenarios and does not interpret free text, fetch context, execute/persist modules or plans, replan at runtime, or synthesize a response.
- Execution requires future `MarketingWorkflowService`, Job, worker, queue, and executable-binding changes.
