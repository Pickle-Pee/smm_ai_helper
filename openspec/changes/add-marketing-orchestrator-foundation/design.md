# Design: Marketing orchestrator foundation

## Responsibility

Orchestrator преобразует пользовательскую цель и доступный project state в минимально достаточный validated plan. Он не является expert module и не выполняет module business logic.

## Interpretation contract

Интерпретация фиксирует:

- requested output;
- decision goal;
- business goal;
- intent;
- object;
- depth;
- execution/learning/mixed mode;
- critical constraints.

## Plan model

Plan содержит nodes и dependencies. Node содержит module ID, objective, inputs, expected outputs, quality gate и conditional next steps. Plan является internal contract и не добавляет публичный API.

## Planning algorithm

1. Interpret request.
2. Check existing context and avoid repeated questions.
3. Detect root-problem risk.
4. Classify data sufficiency.
5. Resolve minimum suitable modules through Registry.
6. Build dependency graph.
7. Validate graph.
8. Return plan or blocking questions.

Первый implementation MAY be deterministic/rule-based. Model-driven planning требует отдельного change и evals.

## Parallelism

Nodes могут быть parallel только если у них нет data dependency и conflicting assumptions. Parallelism metadata не означает немедленный async execution.

## Context packet

Каждый node получает scoped packet. Full conversation dump не является контрактом. BrandProfile, relevant facts, artifacts и evidence передаются по существующим service boundaries.

## Architecture integration

- Single-task requests продолжают использовать `TaskPipelineService`.
- Multi-step plan создаётся отдельным orchestrator component.
- Future execution координируется `MarketingWorkflowService`.
- Durable state хранится в PostgreSQL entities/services.
- Redis transport подключается позже.

## Failure behavior

- Unknown module/alias → plan validation error.
- Dependency cycle → plan validation error.
- Blocking input missing → blocked plan с максимум тремя critical questions.
- Optional input missing → план допускает preliminary/limited result.

## Rollback

Удаление plan boundary не требует data migration; существующий single-task execution остаётся доступным.

