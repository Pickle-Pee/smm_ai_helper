# Prompt governance

## Sources of truth

- `app/prompts/expert_core/v1.0.0.md` — единственный canonical runtime source Expert Core `1.0.0`.
- `docs/product/prompts/orchestrator-production.md` — orchestration policy.
- `docs/product/prompts/module-registry-production.md` — canonical registry policy.
- Specialized module prompts — task-specific expertise only.

`docs/product/expert-core.md` — product contract, а не prompt source. `docs/product/prompts/expert-core-production.md` и DOCX-файлы — archival provenance для initial-import review; loader/composer не читает их и не содержит копию Expert Core body.

## Ownership boundaries

- CORE владеет общими non-negotiable reasoning rules.
- ORCHESTRATOR владеет goal interpretation, planning, routing, quality-gate flow, replanning, synthesis и stopping.
- MODULE REGISTRY владеет descriptors, aliases, activation/return contracts и authority limits.
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
9. Записать size/token/composition evidence в `docs/development/expert-core-verification.md`.

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
