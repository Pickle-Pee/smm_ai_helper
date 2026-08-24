# Marketing Orchestrator product contract

## Responsibility

ORCHESTRATOR управляет качеством процесса принятия решения:

```text
GOAL → EVIDENCE → EXPERTISE → VALIDATION → DECISION → LEARNING
```

Канонический prompt: [`prompts/orchestrator-production.md`](prompts/orchestrator-production.md).

## Core lifecycle

```text
INTERPRET
→ CHECK_CONTEXT
→ DIAGNOSE
→ CHECK_EVIDENCE
→ PLAN
→ EXECUTE
→ VALIDATE
→ REPLAN_IF_NEEDED
→ SYNTHESIZE
→ STOP
```

## Planning rules

- Простой запрос использует один подходящий модуль.
- Complex request получает минимальный dependency graph.
- Независимые nodes могут выполняться параллельно.
- Node, использующий output другого node, выполняется последовательно.
- Critical blocking input нельзя заменять assumption.
- Preferred/optional input не должен блокировать полезный preliminary result.
- Перед дополнительным этапом оценивается value of information.
- Workflow меняется после material finding, если изменился лучший следующий шаг.

## Context rules

Каждый module activation получает ограниченный context packet, а не весь conversation dump. Packet должен содержать только релевантные goal, known facts, upstream findings, evidence, assumptions, constraints, tools и open questions.

## Output rules

Orchestrator не показывает пользователю module dump. Он синтезирует единый ответ с главным выводом, evidence, приоритетными действиями, validation и material risks. Формат адаптируется к сложности запроса.

## Stop conditions

- `ANSWER_OBTAINED`;
- `USER_SCOPE_COMPLETE`;
- `DIMINISHING_INFORMATION_VALUE`;
- `EVIDENCE_SATURATION`;
- `TOOL_OR_DATA_LIMIT`;
- `REVERSIBLE_TEST_IS_BETTER`.

## Architecture constraint

Orchestrator не встраивается как multi-step engine в `TaskPipelineService`. Execution multi-step plans принадлежит `MarketingWorkflowService` и durable Job infrastructure.

