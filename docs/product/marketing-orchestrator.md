# Marketing Orchestrator product contract

## Product responsibility

The full product concept manages decision quality across:

```text
GOAL -> EVIDENCE -> EXPERTISE -> VALIDATION -> DECISION -> LEARNING
```

[`prompts/orchestrator-production.md`](prompts/orchestrator-production.md) is approved product source material for that future concept. It is not a runtime prompt for the deterministic foundation.

## Foundation contract

OpenSpec change `add-marketing-orchestrator-foundation` owns the implementation contract for:

```text
typed request interpretation -> minimal validated plan
```

The lifecycle ends at:

```text
INTERPRET -> CHECK_CONTEXT -> CHECK_EVIDENCE -> PLAN
-> VALIDATE_PLAN -> RETURN_PLAN_OR_BLOCK
```

A future caller supplies structured interpretation and already-authorized, explicitly tagged context. The foundation validates it; it does not infer arbitrary natural language, query BrandProfile/conversation/URL/artifact stores or accept a raw conversation dump.

## Initial deterministic scenarios

- `explicit_single_module_v1`: one canonical Registry module or approved alias, resolved to a one-node plan.
- `new_positioning_v1`: independent `MARKET_ANALYSIS` and `COMPETITOR_ANALYSIS` nodes feed dependent `POSITIONING`.

Unsupported scenarios are rejected, not guessed. Missing required/blocking facts may yield at most three decision-changing questions. Missing preferred/optional facts become limitations.

## Planning-only readiness

Structural validity, data sufficiency, planning status and execution readiness are distinct. Module Registry `1.0.0` has zero execution bindings, so every valid plan remains `PLANNING_ONLY`.

## Future lifecycle and constraints

Execution, runtime quality validation, replanning, synthesis, delivery and learning are future concerns. Execution belongs to `MarketingWorkflowService` after durable Job and worker infrastructure exists.

- Existing API/Telegram traffic and the `TaskRouter` -> `AgentRunner` -> `TaskPipelineService` flow remain unchanged.
- The foundation calls no modules, agents, models or QC and persists no plan/workflow record.
- No separate dispatcher service is created.
- No Orchestrator prompt is copied into Python or added under `app/prompts/orchestrator`.
- Model-driven planning requires a separate OpenSpec change, versioned runtime prompt, evals and call-budget review.
