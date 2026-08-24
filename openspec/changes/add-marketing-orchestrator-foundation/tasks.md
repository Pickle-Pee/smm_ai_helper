# Tasks

## 1. Discovery

- [ ] 1.1 Найти фактические boundaries `TaskPipelineService`, `MarketingWorkflowPersistenceService`, `MarketingRun`, `MarketingArtifact` и agent routing.
- [ ] 1.2 Проверить применимые `AGENTS.md` и существующие OpenSpec capabilities.
- [ ] 1.3 Зафиксировать, какие inputs уже доступны из BrandProfile, conversation facts, URL context и artifacts.

## 2. Contracts

- [ ] 2.1 Добавить internal request interpretation contract.
- [ ] 2.2 Добавить orchestration plan/node/dependency contracts.
- [ ] 2.3 Добавить stop-condition и data-sufficiency enums либо переиспользовать существующие совместимые types.
- [ ] 2.4 Добавить scoped module context packet contract.

## 3. Planner

- [ ] 3.1 Реализовать отдельный planning component, использующий Module Registry.
- [ ] 3.2 Реализовать minimum-sufficient module selection для явно покрытых сценариев.
- [ ] 3.3 Реализовать dependency graph construction.
- [ ] 3.4 Реализовать plan validation: unknown modules, missing dependencies, cycles и blocking inputs.
- [ ] 3.5 Не добавлять execution/queue behavior.

## 4. Tests

- [ ] 4.1 Простой запрос создаёт single-node plan.
- [ ] 4.2 Complex request создаёт dependency-aware plan.
- [ ] 4.3 Independent nodes помечаются как parallelizable.
- [ ] 4.4 Dependent nodes остаются sequential.
- [ ] 4.5 Blocking input возвращает не более трёх critical questions.
- [ ] 4.6 Existing context не запрашивается повторно.
- [ ] 4.7 Registry aliases разрешаются в canonical IDs.
- [ ] 4.8 `TaskPipelineService` не получает multi-step responsibility.

## 5. Documentation and verification

- [ ] 5.1 Обновить `ARCHITECTURE.md` фактическим planning boundary.
- [ ] 5.2 Обновить roadmap.
- [ ] 5.3 Выполнить `python -m compileall app bot`.
- [ ] 5.4 Выполнить `python -m pytest`.
- [ ] 5.5 Выполнить `openspec validate add-marketing-orchestrator-foundation --strict`.
- [ ] 5.6 Сообщить фактические результаты, limitations, API changes и migrations.

