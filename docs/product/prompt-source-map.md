# Prompt source map

## Purpose

This document separates product source material, runtime sources and design history so duplicate routing components and conflicting canonical sources are not created.

## Source precedence

| Domain | Normative contract/runtime source | Supporting source/history | Decision |
| --- | --- | --- | --- |
| Shared reasoning policy | `prompts/expert-core-production.md` | `Общий системный промпт для ИИ(1).docx` | EXPERT CORE production — единственный runtime source |
| Multi-module orchestration | `prompts/orchestrator-production.md` | `Оркестратор.docx`, `Агентский диспетчер задач (1).docx` | Dispatcher не создаётся отдельным runtime layer |
| Module metadata | `app/module_registry/v1.0.0.json` (runtime `1.0.0`) | `prompts/module-registry-production.md` (initial-import material), archival DOCX (history) | JSON is the only runtime descriptor source; routing belongs to future Orchestrator work |

## Reconciliation decisions

Early general prompt concerns are split among Expert Core, Orchestrator, Module Registry and specialized modules. Early dispatcher responsibilities overlap Orchestrator planning; a separate dispatcher would duplicate routing and is not created.

`docs/product/prompts/orchestrator-production.md` is approved version-controlled product source for a broader future lifecycle, not a canonical runtime prompt for `add-marketing-orchestrator-foundation`. The foundation makes no LLM call and creates no `app/prompts/orchestrator`; typed code and deterministic OpenSpec rules own runtime planning behavior.

A future model-driven planner must define one versioned runtime prompt in a separate OpenSpec change with evals, call-budget/token and latency review. Until then, no Orchestrator file is called a canonical runtime prompt.

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

Moving an approved product rule into runtime requires product rationale, an OpenSpec behavior change, one versioned runtime source, tests/evals, conflict review and call-budget review when a model is involved. Legacy DOCX material remains design history rather than runtime source.
