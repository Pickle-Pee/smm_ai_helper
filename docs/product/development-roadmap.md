# Development roadmap

## Completed

- [x] OpenSpec and Codex bootstrap.
- [x] `add-marketing-workflow-persistence`.
- [x] Create and strictly validate `add-expert-core-foundation`.

## Current

- [ ] Review and apply `add-expert-core-foundation`.
- [ ] Evaluate CORE behavior across strategy, content, analytics, promo and trends agents.

## Foundation next

- [ ] `add-module-registry-foundation`.
- [ ] `add-durable-job-persistence`.
- [ ] `add-redis-worker-foundation`.
- [ ] `add-marketing-orchestrator-foundation`.
- [ ] `add-orchestrator-quality-gates`.

## Product vertical

- [ ] `add-competitor-analysis`.
- [ ] `add-competitor-analysis-workflow`.
- [ ] `add-creative-package`.
- [ ] `add-commercial-creative-workflow`.
- [ ] `add-mentor-insight`.
- [ ] `integrate-expert-core-with-marketing-workflows`.
- [ ] `add-telegram-marketing-workflow`.

## Reliability and release

- [ ] `add-job-retries-and-idempotency`.
- [ ] `add-telegram-delivery-worker`.
- [ ] `add-integration-release-gates`.

## Sequencing rules

- Один change реализуется в одной ветке `agent/<change-name>` от актуальной `sale-ready`.
- OpenSpec сначала создаётся и проверяется, затем Codex останавливается.
- Runtime implementation выполняется отдельным apply step.
- `master` получает изменения только release merge после integration в `sale-ready`.
- Roadmap не является implementation spec; исполняемая задача всегда находится в `openspec/changes/<change>/tasks.md`.

