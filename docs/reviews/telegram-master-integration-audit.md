# Интеграционный аудит Telegram production → master

Дата: 2026-10-30 (Europe/Moscow). База после fetch: `4685ce680df524617b2050cc293c592d29d67ed8`.
Production не изменялся; merge, deployment, production-миграции и изменения серверной конфигурации не выполнялись.

## Вывод

Нужен один интеграционный PR от актуального master. Он переносит итоговое дерево #129 + #131
из #134, сохраняет #135/#136 и финальные очищенные документы #132. Старую sale-ready
не интегрировать целиком. Повторный deployment Telegram-меню не требуется.
Это согласование исходников с уже развёрнутой функциональностью, а не подтверждение,
что production уже исполняет новый master с #135/#136.

## Матрица присутствия

| PR | Состояние на момент аудита | Что есть в master / что отсутствует |
| --- | --- | --- |
| [#132](https://github.com/Pickle-Pee/smm_ai_helper/pull/132) | OPEN, base sale-ready, head 61aa4a6 | Оба документа отсутствуют. Перенести только финальное содержимое, без прежних публикаций инфраструктурных подробностей. |
| [#133](https://github.com/Pickle-Pee/smm_ai_helper/pull/133) | OPEN, base sale-ready, head 173d761 | Точных коммитов нет. Эквивалентные dependency fixes уже есть: sqlalchemy[asyncio] (8bb43c3), selectolax<1 (eb7bc9c). Sync Alembic уже исправлен через установленный psycopg3 (ac73995), а не psycopg2. Не переносить de5cd9f/173d761 целиком. |
| [#134](https://github.com/Pickle-Pee/smm_ai_helper/pull/134) | OPEN, base master, head 420df1a | 23 коммита после общего a51a12d отсутствуют; git cherry показывает + для каждого. Отсутствуют durable menu, единая история, private project bindings, /new isolation, source drafts, context epoch admission, saved replay/recovery, contextual Mentor и migration 0013. |
| [#135](https://github.com/Pickle-Pee/smm_ai_helper/pull/135) | MERGED | dd0f87e включён merge ae40b49: strict completed envelope, schema preservation, bounded sends/tokens, uncertain outcome stopping. Сохранить полностью. |
| [#136](https://github.com/Pickle-Pee/smm_ai_helper/pull/136) | MERGED | c09cec2, 1db22cd, b87576c включены merge 4685ce6: diagnostics и opt-in durable retry governance. Сохранить полностью. |

В master уже есть prerequisite история до a51a12d: worker admission 0012, graph runtime,
Copilot interpretations/snapshots, positioning integrations #125/#126 и #128.
Ветка #134 основана на a51a12d; все её 23 коммита ещё не интегрированы.
Ветка #133 основана на sale-ready b231567 и не является обязательной зависимостью master.

## Конфликты и контракты

Пересечение production release с изменениями #135/#136 — только
`app/orchestration_runtime/service.py`. Трёхстороннее применение production diff
воспроизвело конфликт в инициализации `MarketingRun.input_json`:
#131 задаёт history_title, #136 задаёт responses_retry. Сохраняются оба ключа.
Остальные 89 файлов feature diff применились без текстовых конфликтов.

Путь исполнения: bot.main.create_dispatcher → project_navigation / handlers → backend clients →
projects/chat/Copilot routers → ProjectContextService / ProjectHistoryService / ExecutionStore →
GraphExecutionService. PostgreSQL владеет ActiveProjectBinding.version, ProjectSession,
ProjectDiscussionTurn и durable execution receipts; FSM/Redis не становятся источником истины.
Смена контекста и admission сериализуются блокировкой владельца; старые request keys/epochs
не могут создать новый Job после /new. Saved execution replay предшествует повторной генерации.
Mentor и project chat имеют собственные bounded durable claims; #136 остаётся graph-only.

Retry governance сохраняется в том же input_json вместе с title. Reservation/receipt/decision
обновления #136 используют расширение существующего словаря и сохраняют title. Флаг enrollment
остаётся false по умолчанию; существующие unmarked runs сохраняют legacy policy. Уже помеченные
runs остаются governed после отключения enrollment. Новые тесты проверяют оба режима, идемпотентный
start и отсутствие повторного POST после timeout и реконструкции worker.
Никакие provider profiles, Quality Gates или бюджеты #135/#136 не ослабляются.

Отдельный конфликт полного #134 с master — `migrations/env.py`: candidate выбирает psycopg2,
master уже выбирает установленный psycopg3. Поэтому commit 420df1a (env.py + его driver-specific
тест) исключён, master env.py и requirements.txt сохранены. Его цель уже обеспечена master.
Новые Alembic driver tests проверяют текущий psycopg3 без переключения runtime asyncpg.

## Что подтверждено о production

Источник: финальные [report](../operations/telegram-menu-production-rollout.md) и
[manifest](../operations/telegram-menu-production-rollout.manifest.json) #132, а также описание #134.
Это сохранённые подтверждения выполнения/наблюдения 2026-10-27, не новое обследование сервера.
Подробные исходные attestation/backup записи находятся в protected operator storage и здесь
повторно не проверялись. Пользователь также подтвердил, что меню уже развёрнуто и работает.

- Attested runtime candidate: 420df1ae1b90762a494a3fa95df4ee4fa31ef609 (backend/worker/bot).
- До cutover: revision 20261014_0012. В ходе cutover применена только additive 20261026_0013,
  затем schema parity; observed production revision = 20261026_0013.
- Цепочка 0001–0012 — предшественники подтверждённого head; это не отдельные журналы применения
  каждой старой миграции. Других новых production migrations по этим источникам не подтверждено.
- 0013 создаёт project_sessions, active_project_bindings, project_discussion_turns и индексы
  ix_marketing_runs_owner_type_activity / ix_tasks_owner_created. Файл переносится неизменным.
- Backup/restore rehearsal, expanded-schema old-image rehearsal, fenced drain, cutover data
  preservation, readiness и один poller отмечены как выполненные. Downgrade не запускался.
- Реальный Telegram acceptance был waived; smoke использовал actual Dispatcher/backend,
  fake transport и synthetic operator strategy. Paid continuation/semantic quality не проверены.
- Нет подтверждения deployment #135/#136. Наличие этих PR в master не доказывает их presence
  в production. Никакие исторические CI не подменяют текущую интеграционную проверку.

## Конкретный порядок интеграции

1. Зафиксировать base 4685ce6 и создать codex/integrate-telegram-production-master.
2. Применить итоговый feature diff a51a12d..26ec261 (22 source commits ниже); не переносить
   sale-ready, эксперимент #130 или устаревшее переключение драйвера 420df1a.
3. Разрешить input_json сохранением history_title + optional responses_retry. Добавить
   PostgreSQL regression на оба режима и restart; включить его и governance fault injection
   в container-smoke. Driver compatibility проверить против текущего master psycopg3.
4. Перенести только два финальных публичных файла #132 с 61aa4a6 (не cherry-pick всей истории).
5. Выполнить полный python CI и container-smoke, migration/schema parity, persistence,
   Redis recovery, drain и SIGTERM/restart для нового head. Оставить PR открытым для решения пользователя.
6. После отдельного разрешения на merge: включить только интеграционный PR в master;
   #132/#133/#134 закрыть как superseded с ссылкой на него. Сейчас эти PR не закрывались.
   Не переназначать #132 на master: это не гарантирует чистый docs-only diff от sale-ready.
7. Никакого автоматического deployment вслед за интеграцией. Production уже на 0013:
   не делать downgrade/stamp/reapply, не менять revision ID и не создавать duplicate migration.
   Будущее распространение #135/#136 — отдельная задача с отдельной авторизацией.

## Source commit inventory (агрегировано одним интеграционным коммитом)

```text
d1c9f5a3e6a11afc221a98cf41c5482360355b5a fix(telegram): harden bot flows and add saved strategy mentorship
2fcc7814a446804a8f66c0251299f467e6119c3d test(telegram): complete release boundaries and case evidence coverage
9e0e373c8f26ce65c3d257ca53622bb287ab3774 fix(telegram): drain spawned updates before closing bot session
3cec824d2921621c1253181e0fe5b83f04198c53 fix(mentor): validate saved feedback and case reply acknowledgements
27c32023374c80c289a313cd774b1719152a4ecd test(tasks): distinguish contender locks from provider transactions
844837de1eb5849f8bd9d0326ff5acd3eb1ee131 docs(telegram): record hardening evidence and production recovery
a44e6fb5ee2db62859273e258866a328f9121809 docs(telegram): link draft delivery and acceptance status
72ac2bb17ca33a5e0891a3abdf3d88a069d32999 docs(telegram): record successful container and release CI
da196ecbdafb28f80b4d31fc51cc481c8f0666c5 fix(telegram): validate workflow responses and bound ephemeral actions
842681927b7805e72edfcf57a4ee0dfa48633861 fix(mentor): generate durable contextual case dialogue and analyze reports
117b2c49c2779608fe86163e7914a60403b37dd5 fix(copilot): replay committed execution results and expose saved recovery
c36e26f81d6133b9f03742b964ef9aa6b67d397e test(acceptance): retain independent probes and gate remediation in containers
ef0d218211105b3d8d9f9735774983ea53b7fa79 fix(acceptance): preserve pending interpretation validation and receipt invariants
b04685bc586845592f509eababc5388672852926 docs(acceptance): record remediation evidence and all requirement boundaries
b136bc83d9e4c40498ea78f2cfd4043f2eb2f524 feat(telegram): add durable project navigation and isolated context
41a9ff96cd6a05aca8532c33a96dfdaced511991 fix(history): reject task identities beyond database integer range
b98302ff04795a864369b7806a634c4ca56974b7 test(telegram): allow scoped command setup in offline lifecycle probe
db3a2a8e5e1fdf1b27073f6ba3b9d33900e01b6b fix(history): normalize saved activity timestamps to UTC
07b080e2f3d54a6bc4f08d96e63c7199a2c20afb fix(telegram): fence chat admission and persist source drafts
d7da5cd2f647eae05b84c06ae3f5034ef7a1e165 test(telegram): verify additive context admission contract
facd24c75316ab30ace8a656f5c87bb1172c5277 Fence every new Telegram Copilot request by its checked context epoch
26ec261d0ed1d34f9c83be32780208a9b61752f2 Retain stale Copilot admission identities across Telegram redelivery
```

Не переносить:
- de5cd9f: старый psycopg2 fix из #133; superseded master ac73995.
- 173d761: dependency compatibility из #133; superseded 8bb43c3 + eb7bc9c.
- 420df1a: psycopg2 env.py + привязанный к нему тест из #134; сохранён master psycopg3.
- b4d267a / 4abc3f6 / 61aa4a6 как цепочку истории #132; перенесены только два final blobs с 61aa4a6.

## Полный перечень feature-файлов

Diff a51a12d..26ec261 (до integration regression/docs additions):

```text
.github/workflows/ci.yml
ARCHITECTURE.md
README.md
app/main.py
app/marketing_copilot/api_contracts.py
app/marketing_copilot/api_service.py
app/marketing_copilot/execution_store.py
app/marketing_copilot/mentor.py
app/marketing_copilot/mentor_contracts.py
app/marketing_copilot/mentor_metrics.py
app/marketing_copilot/production.py
app/models.py
app/orchestration_runtime/service.py
app/routers/chat_router.py
app/routers/copilot.py
app/routers/projects.py
app/schemas.py
app/services/chat_execution_service.py
app/services/chat_memory_service.py
app/services/chat_service.py
app/services/project_context_service.py
app/services/project_history_service.py
bot/backend.py
bot/copilot_client.py
bot/copilot_contracts.py
bot/copilot_flow.py
bot/delivery.py
bot/handlers/agent_flow.py
bot/handlers/chat.py
bot/handlers/copilot.py
bot/handlers/history.py
bot/handlers/mentor.py
bot/handlers/menu.py
bot/handlers/workflow.py
bot/main.py
bot/operation_guard.py
bot/project_navigation.py
bot/workflow_contracts.py
docs/design/telegram-navigation-and-context.md
docs/development/telegram-copilot-ux.md
docs/development/telegram-hardening-baseline.md
docs/development/telegram-hardening-report.md
docs/operations/telegram-production-runbook.md
docs/reviews/pr129-final-acceptance.md
docs/reviews/pr129-remediation-report.md
docs/reviews/telegram-menu-acceptance.md
migrations/versions/20261026_0013_project_context.py
tests/project_architecture_support.py
tests/release_offline_bot.py
tests/test_case_mentor.py
tests/test_case_mentor_dialogue_postgresql.py
tests/test_case_mentor_postgresql.py
tests/test_chat_context_admission_postgresql.py
tests/test_chat_execution_postgresql.py
tests/test_copilot_api.py
tests/test_copilot_api_postgresql.py
tests/test_copilot_application.py
tests/test_copilot_context_admission_postgresql.py
tests/test_copilot_sync_replay_postgresql.py
tests/test_graph_compiler.py
tests/test_http_security.py
tests/test_marketing_copilot.py
tests/test_module_execution.py
tests/test_new_chat_isolation_postgresql.py
tests/test_pr129_acceptance.py
tests/test_production_graph_worker.py
tests/test_production_rollout_postgresql.py
tests/test_project_context_api.py
tests/test_project_context_postgresql.py
tests/test_project_dialogue_continuity_postgresql.py
tests/test_project_history.py
tests/test_project_history_postgresql.py
tests/test_release_hardening_postgresql.py
tests/test_release_telegram.py
tests/test_source_draft_postgresql.py
tests/test_task_finalization_postgresql.py
tests/test_telegram_action_labels.py
tests/test_telegram_case_mentor.py
tests/test_telegram_copilot.py
tests/test_telegram_copilot_postgresql.py
tests/test_telegram_hardening_flows.py
tests/test_telegram_media_delivery_hardening.py
tests/test_telegram_navigation.py
tests/test_telegram_navigation_fixtures.py
tests/test_telegram_offline_startup.py
tests/test_telegram_operation_lifecycle.py
tests/test_telegram_project_context_postgresql.py
tests/test_telegram_remediation.py
tests/test_telegram_request_identity_postgresql.py
tests/test_telegram_sync_recovery.py
```

Дополнительно: `tests/test_telegram_responses_integration_postgresql.py`,
`tests/test_alembic_driver.py`, этот отчёт, два final rollout документа из #132;
`.github/workflows/ci.yml` включает integration/governance тесты в container gate.
`requirements.txt`, `migrations/env.py`, transport/telemetry/retry-policy/worker/config
из master сохраняются без изменений.

## Validation

Проверены diff/контракты, отсутствие отката #135/#136 и совпадение migration 0013 с candidate.
Локально выполнены 133 offline regression tests (PASS). Дополнительные local PostgreSQL и
remote CI результаты публикуются в описании интеграционного PR и итоговом отчёте вместе с head SHA.
CI старых #133/#134 повторно прочитан через GitHub: python и container-smoke SUCCESS,
включая migration/schema parity и lifecycle gates; это только historical evidence.
Новый PR должен иметь собственные два успешных CI jobs на своём head; пропуски не считаются PASS.
