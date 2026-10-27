# Telegram menu production rollout — NO_GO

Дата проверки: 2026-10-27 (Europe/Moscow). Финальный статус: **NO_GO**.

Production не изменён. Миграции, pause/resume, перезапуск, сборка, pull/tag images,
backup, изменение конфигурации и Telegram updates/sends не выполнялись.
Разрешённый rollout остановлен на обязательном readiness gate: проверенный backup
с восстановлением, наблюдаемый ingress barrier, live drain и проверенный rollback
не подтверждены. Нулевые текущие claims не разрешают cutover при открытом admission.

## Исходное и конечное состояние

Sanitized снимок: [deployment manifest](telegram-menu-production-rollout.manifest.json).
Время наблюдения в manifest — UTC; это read-only снимок, а не действующий drain gate.

| Поле | Проверенное значение |
| --- | --- |
| Hostname | `nl-vmv2-nano` |
| Production directory | `/opt/smm_ai_helper` |
| Checkout SHA до/после | `a51a12d44da602d96a22cb99e26026898c8006a2` |
| Runtime source evidence | По 206 Python-файлов в app/bot/migrations внутри каждого backend, worker, bot совпадают с checkout; расхождений нет |
| Ограничение attestation | OCI revision отсутствует; проверены Python-файлы, не полная воспроизводимая сборка образа и не все assets/config/dependencies |
| Migrate source attestation | Exited container, exit 0; исходники внутри него не проверены |
| Integration branch | После fetch `origin/master` = `a51a12d44da602d96a22cb99e26026898c8006a2` |
| Целевой source SHA | `26ec261d0ed1d34f9c83be32780208a9b61752f2` (PR #131) |
| Dependency SHA | `b04685bc586845592f509eababc5388672852926` (PR #129), предок target |
| RC | Только зафиксирован целевой source SHA; отдельный immutable release image не собран и RC не принят |
| Alembic до/после | `20261014_0012` |
| Целевая миграция | `20261026_0013`, не применена |

Runtime SHA выше подтверждён в указанной области файлов, а не принят на веру по
каталогу Git. После проверок ни checkout, ни application images не заменялись.

## Images и persistent state

Значения ниже — Docker image IDs; RepoDigests, возвращённые daemon, отдельно
сохранены в manifest. Локальная доступность ID не доказывает доступность registry
для восстановления на другом хосте. Архивирование и пробный rollback не выполнены.

| Сервис | Image ID (sha256) | Состояние |
| --- | --- | --- |
| backend | `389f1c45b0fc7b46f5b59b9a371057227d4abd0ab68bf078ce409c0cacfee8c7` | running, healthy |
| worker | `2204a2f905ae12ecaf1ef367b466828313ad393c0ff181167e3915026cdaeef5` | running, healthcheck отсутствует |
| bot | `edf78df9fbe5ac3ad033f45834d08593020e23e1f6683c200948e8a26bc06b4a` | running, healthcheck отсутствует |
| migrate | `f111fe98ccf1794ce05bb1dc05c0085477462a8fd0d695d09dc8f77652592230` | exited 0 |
| db | `7e2070cf6ad06fb3cbbd141b1bafbb7fd5bb63e2b6001e6daf34448eb555e4b3` | PostgreSQL 15, healthy |
| redis | `858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499` | Redis 7 alpine, healthy |

Compose labels всех шести контейнеров указывают только
`/opt/smm_ai_helper/docker-compose.yaml`; effective config проходит `config --quiet`.
SHA256 файла сохранён в manifest. Имена сервисов: db, redis, migrate, backend,
worker, bot. По одному запущенному экземпляру каждого, кроме завершённого migrate.
Это инвентаризация Compose-контейнеров, не доказательство отсутствия всех внешних writers.

Backend/worker используют `smm_ai_helper_smm_images` в `/data/images`; PostgreSQL —
`smm_ai_helper_smm_db_data` в `/var/lib/postgresql/data`. Redis имеет anonymous volume
в `/data`; исходная Compose-конфигурация отключает RDB/AOF. Volumes не изменялись.
Backend опубликован на loopback:8000, PostgreSQL на loopback:5432; bot использует
прямой `http://backend:…` внутри default Compose network. Поэтому внешний reverse
proxy без закрытия bypass не является подтверждённым ingress barrier.

`GET /health` → 200 `{"status":"ok"}`; `GET /ready` → 200 `{"status":"ready"}`.
Redis → `PONG`; `INFO keyspace` не показывает непустых DB. Payload/keys не читались.
Backend, DB, Redis имеют healthy container checks; bot и worker своих checks не имеют.

## Очереди, операции и worker drain

Read-only PostgreSQL transaction дала:

- `worker_admission`: `paused=false`, `epoch=0`.
- `worker_attempts`: 0; `job_executions`: 0 claim tokens, 0 active leases,
  0 future-available entries.
- `jobs`: только `orchestration.module`, 21 succeeded и 23 failed;
  pending/running строк нет. Failed jobs не перезапускались.
- `task_sessions`: 0 finalization tokens; `workflow_deliveries`: пусто.
- В первом снимке pg_stat_activity: 5 idle, 1 active (включая сам probe).
  Это не счётчик принятых HTTP handlers и не доказательство отсутствия provider I/O.

Worker Drain Control код и revision 0012 присутствуют: legacy bootstrap по причине
отсутствия контроля здесь не требуется. Выделенная переменная
`WORKER_DRAIN_DATABASE_URL` отсутствует в backend/worker/bot. Отдельная operator
connection извне и её grants не подтверждены. Credentials приложения не
подставлялись вместо предусмотренных операторских credentials. CLI pause/status
с `--require-drained` не выполнялись. При открытом admission успешный drained gate
не был бы возможен даже при текущих нулевых attempts.

Инвентаризация внешних writers, уже принятых синхронных chat/task/Copilot handlers
и закрытие всех входов не подтверждены. Снимки jobs/Redis не заменяют эти проверки.

## Границы source release и зависимости

Production SHA — общий предок production и target. Между ними 22 коммита,
90 файлов, 9253 добавленных / 506 удалённых строк. PR #129 добавляет 14 коммитов,
51 файл; delta #129 → target #131 — 8 коммитов, 62 файла. Никакие ветки не сливались,
PR #130 не интегрировался, коммиты из sale-ready не переносились.

Минимальная логическая граница feature включает:

1. Сначала dependency #129: durable Copilot execution receipts/recovery,
   Case Mentor/context/feedback, backend recovery API, Telegram contracts и lifecycle.
   Меню импортирует эти реализации; перенос одного keyboard handler недостаточен.
2. PR #131: `bot.main`/menu → `project_navigation` → authenticated `/projects`
   router → `ProjectHistoryService`/`ProjectContextService`. History объединяет
   owner-scoped graph, workflow, task, receipt, legacy и isolated conversations.
3. PostgreSQL владеет selection/version, sessions, discussion, source drafts и
   admission receipts. FSM не является источником истины после restart. Новые
   chat/Copilot DTO добавляют optional request_key/context_version и stale guards.
4. Chat admission/memory и graph start добавляют context fencing; worker entrypoint
   и orchestration worker не меняются. Старые jobs не мигрируются и не переиздаются.

От production до target отсутствует diff в `app/llm`, `app/config.py`,
`app/model_generation_policy.py`, `app/worker.py`. Это source comparison; семантическая
совместимость всех живых операций ещё требует staging. Новые mentor/project
discussion paths способны обращаться к provider при явном продолжении; navigation
должна оставаться без вызовов. Production OpenAI environment не менялось и значения
не выводились.

Единственная новая migration — 0013 поверх 0012. Она добавляет project_sessions,
active_project_bindings, project_discussion_turns и два индекса истории; не удаляет
старые данные. Индексы строятся обычным create_index, поэтому production lock/time
budget не проверен. Additive форма — основание для application rollback с сохранением
схемы, но не доказательство проверенного rollback. Downgrade удаляет новые таблицы
и запрещён как runtime rollback. Новые drafts/receipts используют также существующее
хранилище — старые readers/writers необходимо проверить на восстановленной копии.

Точный target с dependency является кандидатом для последующей проверки. Минимально
безопасный cherry-pick subset в этом запуске не доказан; масштабное обновление не
авторизовано как обход незакрытых gates.

## CI, staging и acceptance

Через GitHub connector проверен workflow run
[40527573406](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/40527573406),
найденный по точному target SHA: completed/success. Jobs `python` (122271197989) и
`container-smoke` (122271198057) completed/success. Python job включает migrations,
schema parity и tests; container job включает disabled external providers,
PostgreSQL/Redis, persistence recreation, worker lanes/recovery/shutdown и graph
SIGTERM/restart. Текущий workflow использует стандартный PR checkout; отдельное
attestation полного checkout/build SHA из job logs здесь не выполнено.

Исторический [acceptance report PR #131](https://github.com/Pickle-Pee/smm_ai_helper/blob/26ec261d0ed1d34f9c83be32780208a9b61752f2/docs/reviews/telegram-menu-acceptance.md)
описывает fake-provider A/B, restart, ownership, stale callbacks и redelivery probes.
Он прочитан как существующее свидетельство, а не новый тест этого rollout.

| Acceptance | Результат этого rollout |
| --- | --- |
| Separate immutable RC + staging DB/Redis | Не создавались после NO_GO discovery |
| Migration/schema parity в новом staging | Не выполнены |
| Fake Telegram menu/history/A/B/restart | Не повторялись; имеются исторические regression/CI свидетельства |
| Captured assembled model context с противоположными A/B фактами | В этом запуске не проверен |
| Ownership, stale callback, duplicate update, legacy/task recovery | В этом запуске не проверены на RC |
| Production /start/history/card/result | Не проверены; target image не запущен |
| Production selection persistence и bot restart | Не выполнены |
| Production чужой проект, /new, stale buttons | Не выполнены |
| Production backend/DB/Redis health | Read-only проверки прошли |
| Production worker lanes функционально | Только metadata/code inventory; runtime acceptance не выполнена |

Второй Telegram poller не запускался, production token для тестов не использовался.

## Backup, readiness gate и rollback

Read-only поиск `/opt` и `/var/backups` до глубины 4 по *.dump, *.sql.gz, *.backup
не нашёл файлов. Это ограниченный поиск, не утверждение отсутствия внешних backups.
Ни свежий backup, ни успешное восстановление в отдельную БД не подтверждены.

| Обязательное условие | Статус |
| --- | --- |
| Backup + tested restore | UNVERIFIED — блокирует |
| Предыдущие immutable image IDs | Зафиксированы; переносимый archive/restore не проверен |
| Предыдущая configuration recovery | Compose path/hash зафиксированы; protected configuration backup не проверен |
| Migration compatibility + lock budget | Additive source review; restore/rehearsal не выполнены — блокирует |
| Required CI | GitHub run и оба jobs success; отдельное build attestation не выполнено |
| Независимое staging acceptance | NOT RUN — блокирует |
| Все workers/writers и live drained gate | NOT PASSED — блокирует |
| Ingress barrier + accepted synchronous handlers | UNVERIFIED — блокирует |
| Ровно один production Telegram poller | Один bot container; отсутствие внешних pollers не доказано |
| Rollback без потери новых данных | Не проверен на восстановленной БД — блокирует |

Ничего не останавливалось. Rollback не требовался и не запускался. Перед будущим
GO нужны protected backup/config/image archives, успешное restore rehearsal,
изолированный RC staging с A/B/restart и проверка rollback старых immutable images
на расширенной схеме. Затем — наблюдаемый ingress barrier для всех входов,
учёт синхронных handlers, dedicated operator credentials и live epoch-fenced drain
для всех workers. Только после этого допустим controlled migration, backend/worker
readiness, замена единственного poller и production acceptance. Старые application
images восстанавливаются с сохранением текущей БД, tables и артефактов; без downgrade
и без повторной генерации незавершённых запросов.

## Provider calls и ограничения

Инструменты этого запуска выполняли только hostname/Git/Docker inspect/config,
чтение source hashes, read-only SQL aggregates, Redis PING/INFO и health/readiness.
Ни generation endpoint, ни provider API, ни Telegram transport не вызывались.
Следовательно, rollout probes не инициировали платных вызовов. Продолжавшая работать
production могла обслуживать независимый пользовательский трафик; глобальное
отсутствие provider calls не измерялось и не заявляется. Секреты и пользовательские
payloads не включены в manifest/report.

Итог: **NO_GO**. Меню на production не развёрнуто и его работа там не подтверждена.
