# Prompt source map

## Purpose

Документ фиксирует, какие предоставленные материалы являются нормативными, а какие используются только как design history. Это предотвращает одновременное появление нескольких компонентов с одинаковой ответственностью.

## Source precedence

| Domain | Normative source | Supporting/legacy sources | Decision |
| --- | --- | --- | --- |
| Shared reasoning policy | `prompts/expert-core-production.md` | `Общий системный промпт для ИИ(1).docx` | EXPERT CORE production — единственный runtime source |
| Multi-module orchestration | `prompts/orchestrator-production.md` | `Оркестратор.docx`, `Агентский диспетчер задач (1).docx` | Dispatcher не создаётся отдельным runtime layer |
| Module metadata | `app/module_registry/v1.0.0.json` (runtime `1.0.0`) | `prompts/module-registry-production.md` (initial-import material), archival DOCX (history) | JSON is the only runtime descriptor source; routing belongs to future Orchestrator work |

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

Ранний реестр использован как каталог capabilities и aliases. Production Markdown is approved initial-import material; the versioned JSON defines runtime descriptors. This foundation does not activate routing guidance or change current task routing.

## Normative editing rule

Изменение production prompt должно сопровождаться:

1. Product rationale.
2. OpenSpec behavior change, если меняется наблюдаемое поведение.
3. Version increment.
4. Tests/evals for the changed rule.
5. Review влияния на token budget и conflicts.

DOCX-файлы считаются source history. For module metadata, `app/module_registry/v1.0.0.json` is the sole runtime source; Markdown holds rationale, governance, and import material without duplicating runtime descriptors.

