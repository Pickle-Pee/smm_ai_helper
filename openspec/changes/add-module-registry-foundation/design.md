# Design: Module registry foundation

## Context

Production Module Registry описывает canonical modules, aliases, inputs, outputs, tools, quality gates, handoffs и authority boundaries. Реестр должен быть декларативным и не создавать параллельный runner.

## Goals

- Один источник истины для module metadata.
- Typed contracts для безопасной маршрутизации.
- Fail-fast validation при duplicate IDs, invalid aliases и broken handoffs.
- Простое расширение через последующие OpenSpec changes.

## Proposed design

### Registry boundary

Добавить read-only registry provider/service, возвращающий immutable descriptors. Точное расположение выбирается после inspection текущей структуры и должно соответствовать применимым `AGENTS.md`.

### Descriptor

Descriptor содержит canonical ID, type, purpose, applicability, dependency requirements, outputs, tool flags, quality gate, handoffs, aliases и authority limits.

### Alias resolution

Alias нормализуется только в canonical ID. Alias не создаёт второй descriptor. Collision двух aliases или alias с canonical ID считается configuration error.

### Validation

При startup/test validation проверяются:

- uniqueness IDs;
- uniqueness aliases;
- valid enums;
- handoff targets exist;
- required fields non-empty;
- no self-handoff unless explicitly allowed;
- tool flags use supported capabilities.

### Integration

Существующий router/agent selection layer получает registry через dependency injection или текущий project convention. Registry не импортирует runner, services, database или Telegram layer.

## Source precedence

`docs/product/prompts/module-registry-production.md` — нормативный product source. Ранний реестр используется только как history.

## Rollout

1. Add models and static registry.
2. Add validation and tests.
3. Adapt existing routing lookups without behavior expansion.
4. Verify current agents remain covered.

## Rollback

Вернуть прежний lookup/composition boundary. Data rollback не требуется.

## Risks

- Слишком раннее моделирование всех будущих outputs. Mitigation: хранить metadata, не реализовывать module business types вне текущего scope.
- Registry становится service locator. Mitigation: registry предоставляет descriptors, но execution остаётся у runner/orchestrator.
- Prompt и code расходятся. Mitigation: explicit version и contract tests.

