# Change: Add marketing orchestrator foundation

## Why

Complex marketing requests require dependency-aware module planning, context scoping and synthesis. Current single-task execution must remain intact, while future competitor → creative → mentor scenarios need a dedicated orchestration layer aligned with durable workflow persistence.

## What changes

- Добавляется internal orchestrator planning boundary.
- Добавляются request interpretation и orchestration plan contracts.
- План использует canonical Module Registry.
- Добавляются dependency types, sequential/parallel rules и stop conditions.
- Добавляется minimal context packet building.
- Добавляется deterministic plan validation.

## Impact

- `TaskPipelineService` не становится workflow engine.
- Orchestrator planning не исполняет Jobs до отдельной execution integration.
- Public API и database schema не меняются.
- `MarketingWorkflowService` остаётся владельцем future multi-step execution.

## Dependencies

- `add-expert-core-foundation`.
- `add-module-registry-foundation`.
- До runtime execution также требуются `add-durable-job-persistence` и `add-redis-worker-foundation`.

## Out of scope

- Redis/worker implementation.
- Job persistence.
- Реализация competitor/creative/mentor modules.
- Automatic execution каждого plan node.
- LLM-based QC.
- Изменение Telegram UX.

