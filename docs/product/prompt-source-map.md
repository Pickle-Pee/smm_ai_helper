# Prompt source map

## Purpose

Документ фиксирует, какие предоставленные материалы являются нормативными, а какие используются только как design history. Это предотвращает одновременное появление нескольких компонентов с одинаковой ответственностью.

## Source precedence

| Domain | Normative source | Supporting/legacy sources | Decision |
| --- | --- | --- | --- |
| Shared reasoning policy | `prompts/expert-core-production.md` | `Общий системный промпт для ИИ(1).docx` | EXPERT CORE production — единственный runtime source |
| Multi-module orchestration | `prompts/orchestrator-production.md` | `Оркестратор.docx`, `Агентский диспетчер задач (1).docx` | Dispatcher не создаётся отдельным runtime layer |
| Module metadata and routing | `prompts/module-registry-production.md` | `Реестр модулей.docx` | Production registry — единственный canonical registry |

## Reconciliation decisions

### General system prompt vs Expert Core

Ранний общий промпт смешивает роль CMO, методы, routing, formulas и quality rules. В production-архитектуре ответственность разделена:

- общие reasoning rules → Expert Core;
- routing и workflow → Orchestrator;
- доступные эксперты и контракты → Module Registry;
- task-specific methods → module prompts.

### Dispatcher vs Orchestrator

Агентский диспетчер и ранний оркестратор решают похожие задачи: intent classification, data sufficiency, depth, module selection и response format. Создание обоих компонентов привело бы к двойной маршрутизации. Поэтому dispatcher requirements включаются в Orchestrator, но отдельный Dispatcher service не создаётся.

### Early registry vs Production registry

Ранний реестр использован как каталог capabilities и aliases. Production registry определяет окончательные module IDs, activation/return contracts, statuses, authority boundaries, routing precedence и handoffs.

## Normative editing rule

Изменение production prompt должно сопровождаться:

1. Product rationale.
2. OpenSpec behavior change, если меняется наблюдаемое поведение.
3. Version increment.
4. Tests/evals for the changed rule.
5. Review влияния на token budget и conflicts.

DOCX-файлы после принятия этого пакета считаются исходными материалами, а Markdown-файлы в репозитории — version-controlled source of truth.

