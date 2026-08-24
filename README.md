# AI Marketing System repository package

Этот пакет подготовлен для копирования в корень репозитория `smm_ai_helper`.

## Содержимое

- `docs/product/ai-marketing-system.md` — продуктовая архитектура системы.
- `docs/product/prompt-source-map.md` — карта исходных DOCX и нормативных версий.
- `docs/product/expert-core.md` — продуктовый контракт EXPERT CORE.
- `docs/product/marketing-orchestrator.md` — продуктовый контракт ORCHESTRATOR.
- `docs/product/module-registry.md` — продуктовый контракт MODULE REGISTRY.
- `docs/product/development-roadmap.md` — порядок OpenSpec changes.
- `docs/product/prompts/` — канонические production-промпты, преобразованные в Markdown.
- `docs/development/prompt-governance.md` — правила владения и изменения промптов.
- `openspec/changes/add-module-registry-foundation/` — первый новый change после EXPERT CORE.
- `openspec/changes/add-marketing-orchestrator-foundation/` — планирование multi-module workflows.
- `openspec/changes/add-orchestrator-quality-gates/` — quality gates, evidence/confidence propagation и replanning.

## Перед копированием

1. Не заменять существующий `openspec/changes/add-expert-core-foundation`: он уже создан и валидирован отдельно.
2. Скопировать содержимое пакета в корень репозитория с сохранением путей.
3. Проверить `git diff` и поправить ссылки, если фактические имена существующих документов отличаются.
4. Выполнить `openspec validate --all --strict`.
5. Не применять сразу все changes. Один change = одна ветка = один PR.

## Нормативный порядок реализации

1. Завершить и проверить `add-expert-core-foundation`.
2. Создать/применить `add-module-registry-foundation`.
3. Реализовать `add-durable-job-persistence` и `add-redis-worker-foundation`.
4. Создать/применить `add-marketing-orchestrator-foundation`.
5. Создать/применить `add-orchestrator-quality-gates`.
6. Подключать конкретные competitor, creative и mentor modules отдельными changes.

