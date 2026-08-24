# Prompt governance

## Sources of truth

- `docs/product/prompts/expert-core-production.md` — shared reasoning policy.
- `docs/product/prompts/orchestrator-production.md` — orchestration policy.
- `app/module_registry/v1.0.0.json` — canonical runtime module descriptors, version `1.0.0`.
- `docs/product/prompts/module-registry-production.md` — approved initial-import material, not runtime data.
- Specialized module prompts — task-specific expertise only.

## Ownership boundaries

- CORE владеет общими non-negotiable reasoning rules.
- ORCHESTRATOR владеет goal interpretation, planning, routing, quality-gate flow, replanning, synthesis и stopping.
- MODULE REGISTRY владеет read-only descriptors, aliases, internal activation/return contracts и authority limits; current task routing and execution remain outside it.
- Modules владеют domain methods и module-specific outputs.

Одинаковое правило не должно копироваться во все слои. Если правило общее — оно принадлежит CORE. Если оно управляет workflow — ORCHESTRATOR. Если описывает capability — REGISTRY. Если относится к методике эксперта — module prompt.

## Change process

1. Определить owner правила.
2. Описать observable behavior в OpenSpec.
3. Изменить один canonical source.
4. Обновить explicit version.
5. Добавить deterministic tests и, где нужно, model-based evals.
6. Проверить prompt conflicts, ordering и duplicate injection.
7. Измерить token overhead и latency на representative scenarios.
8. Обновить product docs и roadmap.

For Module Registry changes, descriptor content is edited once in the versioned JSON. Python constants and Markdown must not duplicate descriptors. Import/version evidence belongs in `docs/development/module-registry-verification.md`, optionally with normalized JSON SHA-256.

## Review checklist

- Инструкция сформулирована один раз.
- Нет конфликта CORE и module prompt.
- Нет второго routing layer.
- Пользовательский context не помещён в static prompt.
- Dynamic/current facts не зашиты как timeless truth.
- Prompt не требует раскрывать chain-of-thought.
- Простые запросы не обязаны использовать complex response template.
- Prompt не обещает гарантированный marketing result.
- Изменение имеет rollback path.

