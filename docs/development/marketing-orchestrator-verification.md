# Marketing Orchestrator foundation verification

## Identification

- Branch: `agent/add-marketing-orchestrator-foundation`
- Base `origin/sale-ready`: `534f98d37a2e2f4c74953383a0ea515a38ab76bb`
- Reconciliation commit: `125bb63269e0094eecfa1210b6105c05fd2b3bec`
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

Node order is `market_analysis`, `competitor_analysis`, `positioning`. Edge order is `competitor_analysis -> positioning`, then `market_analysis -> positioning`. The fixed verification fixture produces plan ID `92f335aff5a29d7c2492f7f387d58819f09a0ddd650f6e8f83037ca2ab5939bc`; equivalent inputs reproduce it.

## Context, questions, and validation evidence

Tests prove only authorized module/scenario-tagged facts enter packets; unrelated and unauthorized secret facts are excluded; independent nodes receive no upstream findings; positioning receives findings only from its declared dependencies; known inputs suppress questions; missing blocking keys are deduplicated and capped at three; preferred/optional gaps become limitations; and nested values remain immutable.

Malformed fixtures independently cover duplicate node IDs, unresolved/unknown modules, missing targets, self-edges, cycles, invalid parallel groups, output/gate mismatches, duplicate/excess/known-input questions, executable readiness with zero bindings, and unsupported graphs.

## Readiness and isolation

- Structural validity, data sufficiency, planning status, and execution readiness are separate.
- Every valid plan is `PLANNING_ONLY`.
- Tests/source isolation show zero agent, model, prompt, QC, database-session, workflow-persistence, Redis, queue, worker, module-execution, or external-service calls.
- Existing `AgentRegistry`, public DTOs, routers, `TaskRouter`, `AgentRunner`, and `TaskPipelineService` are unchanged.
- No product Orchestrator prompt is read and no `app/prompts/orchestrator` exists.

## Commands and results

| Command | Exit | Result |
| --- | ---: | --- |
| `.venv\Scripts\python.exe -m pytest -q tests/test_marketing_orchestrator.py tests/test_module_registry.py tests/test_agent_registry.py tests/test_task_router.py tests/test_task_pipeline_service.py tests/test_marketing_workflow_persistence_service.py` | 0 | 82 passed, 6 existing deprecation warnings |
| `.venv\Scripts\python.exe -m pytest -q` | 0 | 182 passed, 9 existing deprecation warnings |
| `.venv\Scripts\python.exe -m compileall app bot` | 0 | compiled successfully |
| `openspec validate add-marketing-orchestrator-foundation --strict` | 0 | valid |
| `openspec validate --all --strict` | 0 | 11 passed, 0 failed |
| `git diff --check` | 0 | no whitespace errors |

Warnings are existing Pydantic class-config and naive `datetime.utcnow()` deprecations; this change does not modify those areas.

## Impact and limitations

- API/Telegram/database/model/migration impact: none; no Alembic migration.
- Routing/pipeline compatibility: unchanged; compatibility tests pass.
- LLM/QC/persistence/Redis/queue/worker impact: none.
- Planning is limited to the exact two scenarios and does not interpret free text, fetch context, execute/persist modules or plans, replan at runtime, or synthesize a response.
- Execution requires future `MarketingWorkflowService`, Job, worker, queue, and executable-binding changes.
