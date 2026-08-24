# Change: Add marketing orchestrator foundation

## Why

Future multi-step marketing workflows need a deterministic boundary that turns an already structured request into the smallest valid planning graph. The current single-task pipeline must remain unchanged, and the metadata-only Module Registry must not be mistaken for executable module infrastructure.

## What changes

- Add an internal immutable `RequestInterpretation` supplied by a future authorized caller; arbitrary natural language is not inferred.
- Add deterministic planning-only contracts for plans, nodes, graph dependencies, input requirements and scoped context packets.
- Add a fixed initial scenario catalog: an explicit registered single-module request and `new_positioning_v1` (`MARKET_ANALYSIS` plus `COMPETITOR_ANALYSIS`, then `POSITIONING`).
- Resolve aliases through the read-only Module Registry and return canonical module IDs only.
- Validate graph structure, Registry descriptor compatibility, data sufficiency, deterministic ordering and planning-time stop/block conditions.
- Separate structural validity, data sufficiency, planning status and execution readiness. Registry `1.0.0` plans remain `PLANNING_ONLY` because every execution binding is absent.
- Add a durable verification template for the later implementation task.

The foundation responsibility is exactly:

```text
typed request interpretation -> minimal validated plan
```

## Impact

- Internal planning contracts only; no public DTO or endpoint changes.
- No database schema, migration or persistence changes.
- Existing API, Telegram, `TaskRouter`, `AgentRunner` and `TaskPipelineService` behavior remains unchanged.
- Future plan execution belongs to `MarketingWorkflowService` after durable Job and worker infrastructure exists.

## Dependencies

- Completed Expert Core foundation.
- Completed Module Registry `1.0.0` foundation.
- Future execution additionally requires durable Job persistence, Redis transport and workers.

## Out of scope

- Free-text interpretation, LLM planning, runtime Orchestrator prompt loading or an `app/prompts/orchestrator` resource.
- A separate dispatcher component.
- API or Telegram integration and changes to existing single-task routing.
- Module/agent invocation, QC, synthesis, replanning after runtime findings or workflow execution.
- `MarketingRun`/`MarketingArtifact` creation, plan persistence, Jobs, queues, Redis or workers.
- Registry execution bindings, module implementations, database changes, migrations or unrelated refactoring.

## Source governance

`docs/product/prompts/orchestrator-production.md` remains approved product source material, not a runtime prompt for this deterministic foundation. `docs/product/marketing-orchestrator.md` is the product contract; this OpenSpec change is the implementation contract. Planning behavior is owned by typed code and the explicit deterministic rules approved here. A model-driven planner requires a separate OpenSpec change, versioned runtime prompt, evals and call-budget review.
