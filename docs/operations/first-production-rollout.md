# Первый production rollout #122 + #123

Дата подготовки: 15 октября 2026 (Europe/Moscow). Репозиторий
`Pickle-Pee/smm_ai_helper`; integration branch проверена: `master`.
Release source: **`c23dfb2cfc3cfab7cd34fe6226b67404d7d0c166`**, включает merge
#122 `f964237da71132a4334d5a33f3d1cfb11b54995c` и #123.
Production target со слов оператора: `nl-vmv2-nano`, `/opt/smm_ai_helper`.

**Текущий вердикт: NO-GO.** Production не исследован и доступ к нему не разрешён.
Этот документ и collector подготовлены для независимого ревью. Ни чтение
production, ни migration/deployment, ни provider calls этим документом не разрешены.
Сначала требуется отдельное разрешение на read-only reconnaissance; после него
нужны ревью фактической топологии, заполненный evidence record и отдельное разрешение
на maintenance/cutover. Даже разрешение на collector не разрешает cutover.

## 1. Что установлено и чего пока нет

| Уровень доказательства | Результат |
| --- | --- |
| Код точного release SHA | Оба claim boundary защищены, PostgreSQL владеет admission/epoch/attempt markers; migration 0012 additive и **initially open** |
| CI точного SHA | [CI 38650353546](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/38650353546): `python` и `container-smoke` success. Проверены статусы отдельных steps: миграции, `alembic check`, pytest, оба lane, persisted pause/restart и fake-provider recovery |
| Локально в этой подготовке | Результаты и ограничения в [validation record](first-production-rollout-validation.md); CI и прошлые отчёты не выдаются за текущие локальные проверки |
| Фактический production | Ничего не проверено: listeners, proxy, процессы/реплики, overrides, DB identity/schema/grants, jobs/leases, images/volumes и доступность backup неизвестны |

Старый [#122 contract](telemetry122-worker-deployment-plan.md) и
[Worker Drain Control](worker-drain-control.md) объясняют reusable admission gate.
Этот документ задаёт единый **первый bootstrap**. Пятифайловый overlay из подготовки
`39d369d` не является release candidate и не устанавливает #123.

## 2. Topology assessment по репозиторию

```text
Telegram polling → bot.main / handlers + copilot_flow → authenticated HTTP
                                                        ↓
direct host clients → 127.0.0.1:8000 → backend / app.main:app
Docker clients       → backend:8000 ↗       ↓
                                  PostgreSQL durable state ← worker app.worker
                                  Redis wakeup hints       ← fixed + graph lanes
                                  media volume shared backend/worker
```

`docker-compose.yaml`: db PostgreSQL 15, redis 7-alpine, migrate, backend, worker,
bot; default Compose network. Backend binds `0.0.0.0:8000` **в контейнере**, port
published `127.0.0.1:8000` на host; DB published `127.0.0.1:5432`. Worker имеет
fixed/graph lanes в **одном процессе**, concurrency по Settings по умолчанию 2/1.
Bot запускает aiogram polling и delivery task; webhook в этом entrypoint нет.
`smm_db_data` хранит DB, `smm_images` монтируется в `/data/images` backend/worker.
`migrate` автоматически входит в dependency chain backend/worker при обычном `up`.
`restart: unless-stopped` может оживить процесс, если просто послать ему SIGTERM.

Это описание исходного Compose, не утверждение о сервере. `API_BASE_URL`
конфигурируется; localhost publication не исключает host reverse proxy, SSH tunnel,
Docker internal clients, host-network containers, IPv6 ingress, NAT и прямой DB
writer. Nginx/Traefik/maintenance mode не обнаружены в tracked deployment files;
их наличие на сервере не предполагается. Unit/timer/cron и другие проекты тоже
должны войти в inventory. Один обнаруженный worker не доказывает, что он единственный.

### Authoritative producer/execution map

| Вход / внутренний путь | Создание / последующее выполнение |
| --- | --- |
| `POST /workflows` | `app/routers/workflows.py` → `MarketingWorkflowService.start` → `_enqueue` при полном context → `marketing.step` + JobExecution |
| `PATCH /workflows/{run_id}/context` | `.context` → `_enqueue`, когда context стал полным |
| `POST /workflows/{run_id}/continue` | `.continue_run` → `_enqueue` creative/mentor после сохранённого predecessor |
| `POST /copilot/execute` | router → `CopilotAPIService.execute` (`api_service.py`) → длительная intent interpretation / extraction → `MarketingCopilotService.execute` → WORKFLOW → `GraphExecutionService.start_compiled_run` → `_advance_locked` → `orchestration.module` |
| Graph internal `advance`, accepted `finish`, optional terminal `fail` | `_advance_locked` создаёт следующие dependency-ready jobs в транзакции с accepted state |
| Fixed/graph retryable failure | Перенос availability существующей JobExecution, сохранение durable retries; будущий retry тоже должен завершиться до legacy cutover |
| Telegram free text, continuation, `/analyze`, workflow callback | HTTP клиенты `bot/copilot_client.py`, `bot/backend.py`, handlers workflow/copilot → четыре routes выше |
| Generic persistence API | `app/services/job_persistence_service.py:create_job`; два текущих callers: fixed `_enqueue`, graph `_advance_locked`; out-of-repo writers неизвестны |

Выполнение: `app.worker.main` → `run_lane` → fixed `MarketingWorkflowService.claim`
или graph `GraphExecutionService.claim` → provider I/O без удержания DB transaction
→ fenced finish/fail → release exact attempt marker. Redis только hints; DB due
scan восстанавливает потерянные hints. Owner всех leases/retries/artifacts — DB.

`PUT /workflows/profile`, reads, delivery retry и `/internal/delivery/*` не создают
эти worker jobs. `/chat`, standalone `/tasks`, images и deprecated agents API
имеют самостоятельные вызовы, не эти два job kinds. Закрытие **всего backend**
в предлагаемом bootstrap временно затронет и их; это требует maintenance window.
Admission control #123 само по себе эти routes не закрывает.

## 3. Один read-only collector

[`scripts/production_rollout_readonly.py`](../../scripts/production_rollout_readonly.py)
переиспользует проверенные при подготовке `39d369d` приёмы audit:
bounded commands, safe exceptions, source hashes и READ ONLY REPEATABLE READ SQL,
включая старые metadata-anomaly checks. Это новый ограниченный collector, не
installer; он не переносит старые cutover predicates и не читает raw logs/payloads.
Все новые проверки имеют собственную локальную regression coverage.

Локально, без production/network:

```powershell
python scripts/production_rollout_readonly.py manifest --repo . > release-manifest.json
```

Проверить побайтовое совпадение с
[`first-production-rollout.manifest.json`](first-production-rollout.manifest.json)
после JSON decode (formatting несущественен). Manifest — source identity, не image
digest и не разрешение. Для collector нужен доступ к Git object точного target SHA;
его отсутствие даёт STOP, collector сам не fetch'ит на сервере.

**Только после отдельного разрешения на чтение**, через существующий проверенный
операторский доступ, доставить reviewed script + manifest в защищённый staging
каталог существующего host account (не создавать SSH users/keys/sudo rules).
Проверить SHA256 перед выполнением; staging files owned by operator/root, без
group/world write, symlinks и небезопасных ancestors. Не размещать новый installer
в `/app` и не изменять runtime bind mounts ради collection.

Пример **будущей** server-side invocation, не выполнявшейся при подготовке:

```bash
cd /opt/smm_ai_helper
umask 077
python3 /REVIEWED-STAGING/production_rollout_readonly.py collect \
  --manifest /REVIEWED-STAGING/release-manifest.json --execute-read-only \
  > /REVIEWED-EVIDENCE/recon.json
rc=$?
# rc=2 + schema=first_rollout_recon.v1 means collected, still NO_GO.
# schema absent / verdict=STOP / missing fields means collection failed.
test "$rc" -eq 2
```

Точный hostname/path обязательны. Docker API принудительно local Unix socket,
remote contexts и SSH не используются. `/proc`, host и container namespace
listeners (`ss`, `nsenter`), все Docker containers/images/networks/volumes,
Compose label file list + resolved config fingerprints, host process PID/PPID/
start_ticks/network namespace/command hashes, systemd/timers/cron/firewall hashes,
Git/config/source/package hashes и database aggregates собираются без env values.
`docker inspect`/Compose config читаются только в памяти; stdout — selected metadata.
SQL работает с read-only transaction, connect/statement/lock timeouts и rollback.
Никаких provider imports, HTTP POST, Redis mutations или docker logs.
`docker exec python -B` создаёт короткий **read-only helper process**, не worker;
это единственное выполнение внутри существующих containers, не restart/startup.

Optional protected `WORKER_DRAIN_DATABASE_URL` из operator environment передаётся
отдельному restricted-role probe через stdin, никогда через args/Compose environment
override. Collector не сохраняет URL. Без него operator role остаётся unverified.
До 0012 отсутствие control tables ожидаемо, privileges повторно проверяются после
миграции. Прямой operator DB connect должен иметь тот же identity fingerprint,
что app/worker probes; при proxy/socket разнице требуется отдельное доказательство
того же кластера/DB, простое несовпадение не разрешается игнорировать.

Collector всегда `NO_GO`, `inventory_complete=false`; успешная collection никогда
не превращается в deploy gate. Snapshot не атомарен между host/Docker/DB; повторить
после topology changes. Поле `unavailable`, unreadable `/proc`, неизвестный process,
отсутствующий probe или config drift требуют разбора. Hashes firewall/cron/systemd
показывают изменение, **не семантику правил или полноту writer inventory**. Оператор
должен локально сверить их с утверждёнными конфигурациями, дать sanitized role map
для каждого неизвестного PID/service/namespace и объяснить каждый listening port.
Не присылать необработанные rules/units/logs/env/query text в чат.

## 4. Bootstrap barrier: минимальная условно применимая схема

Для repo Compose без доказанного proxy предпочтён **graceful shutdown всех API
producer instances и удержание их выключенными**. Это внешний относительно legacy
worker barrier: исчезают сами API listeners, поэтому нет обхода через Telegram,
Docker DNS или direct backend access. Новый proxy/firewall framework не нужен.
Схема применима только после inventory всех API/direct writers и проверки реального
server shutdown lifecycle. До этого **NO-GO**, а не готовая универсальная команда.

Порядок установки barrier и completion proof:

1. Один ответственный оператор владеет maintenance window; automation/deploy/scheduler
   не может перезапускать API/bot/worker или исполнять прямой writer. Сохранить restart
   policies и identity каждого процесса. Запретить auto-restart **до** посылки TERM
   существующими Docker/systemd controls. Не считать manual signal эквивалентом
   `compose stop`; `unless-stopped` должен быть реально удержан.
2. Приостановить Telegram intake существующим polling lifecycle, без logout,
   deleteWebhook/drop_pending_updates, purge updates и второго polling instance.
   Не убивать активные bot handlers ради доказательства. Уже принятые backend calls
   учитываются API drain независимо от bot HTTP timeout/disconnect.
3. Для каждого backend отправить **один SIGTERM** настоящему server/master process
   с удержанным restart. Например, после проверки PID1/entrypoint Docker позволяет
   `docker kill --signal=TERM <verified-container-id>`: здесь это TERM, не SIGKILL.
   Не использовать обычный `compose stop` с коротким default kill timeout. До
   следующего шага listeners должны быть закрыты во всех IPv4/IPv6 namespaces;
   никакого alternate socket/process/hot reload supervisor. Existing accepted
   connections/handlers должны получить возможность нормально завершиться.
4. Дождаться **graceful completion каждого API process**, не просто отсутствия TCP
   connections. Проверить фактическую версию server/ASGI и что graceful timeout не
   cancels tasks. Нужны наблюдаемые shutdown-start → requests/tasks drained →
   lifespan shutdown complete → process exit с нормальным status, без timeout,
   cancellation/forced kill/restart/OOM. Наблюдать только bounded lifecycle flags;
   raw logs не экспортировать. Если таких сигналов нет, заранее воспроизвести на
   точном runtime с fake held Copilot call либо добавить отдельно reviewed bounded
   in-flight accounting; **в текущем collector такого счётчика нет**.
5. Подтвердить, что ни один accepted request/transaction не оставлен в другом
   API process/task/child. DB active-session count — только corroboration, не
   request counter: ожидающий внешнего LLM request может не иметь DB session.
   Клиентский timeout, bot exit, log silence, два пустых DB snapshots и истечение
   `HTTP_TIMEOUT` не доказывают завершение. Не обрывать backend, пока accepted
   request может записать late graph job.
6. Удержать API/bot/direct-writer closure до resume. На время запуска нового
   backend в postflight потребуется **доказанное network/request isolation** всех
   его callers; если такого existing механизма нет, оставить backend выключенным
   до resume и считать его start частью снятия ingress barrier. Проверки его
   исходников/image выполнять offline, его health/readiness — после resume.

После полного exit всех producers late graph start невозможен только при
доказанном отсутствии иных writers. Существующий worker может создавать
descendants; поэтому затем нужен полный legacy drain и остановка всех workers.
Если требуется сохранять API доступным, alternative — имеющийся request-level
maintenance gate на четырёх routes плюс доказанная блокировка **всех** обходов,
in-flight accounting и тот же accepted-request drain. Наличие такого gate пока
не доказано; устанавливать его вслепую нельзя.

### Telegram retries и maintenance semantics

В polling режиме Telegram хранит ещё не подтверждённые updates, но aiogram может
подтвердить update до окончания отдельного handler. Поэтому остановка bot не
обещает replay всех in-flight messages. MemoryStorage pre-run clarification
недолговечен; bot restart может потерять его. Не объявлять exactly-once maintenance.
Нужны reviewed maintenance notice/recovery policy и fixture-проверка на фактической
версии aiogram: queued updates сохраняются; тот же actor/request_key/effective plan
даёт один run; timeout после backend commit восстанавливается reads
`/copilot_runs`/`/copilot_status` или `/runs`; смена plan даёт conflict.
Не пересылать неоднозначный запрос с новым key автоматически. Synchronous
DIRECT/SINGLE не cached и retry может повторить provider work. `Retry-After` не
обрабатывается автоматически текущими clients; `bot/backend.py` возвращает ошибку,
CopilotClient классифицирует 503 как temporary. При невозможности обеспечить
приемлемое восстановление in-flight Telegram updates — **NO-GO**. Не отправлять
реальные тестовые Telegram/provider requests в этом задании.

## 5. Release scope / provenance / compatibility

Release candidate — **цельный application image точного c23dfb2**, не mixed code
overlay. От base до #122/#123 runtime delta:
`app/llm/{openai_text,telemetry}.py`, `app/models.py`,
`app/orchestration_runtime/{contracts,service,worker}.py`,
`app/workflows/service.py`, `app/worker.py`, `app/worker_control.py`,
`app/services/worker_drain_service.py`, migration
`migrations/versions/20261014_0012_worker_admission.py`.
Build/runtime files и **все** app/bot/migrations/prompts проверяются полным manifest,
а не только delta. Фактический production base неизвестен: если он не attested
`55b0987`, нужна карта всех intermediate changes/contracts, не предполагать, что
перечисленная delta — вся разница с production.

Минимальный service replacement — migrate one-shot из target image + все workers.
Backend/bot можно сохранить на их attested immutable images, если local/CI
compatibility и actual production versions подтверждены: 0012 только добавляет
tables, DTO/graph routing/artifact contracts #122/#123 не меняет, старые producers
не обязаны знать admission. Это **не** разрешение для неизвестного legacy backend:
сверить его source/DB schema/graph v1/v2/registry contracts. Если совместимость
не доказана, review scope расширяется на backend/bot из того же target image;
barrier удерживается на весь переход. DB/Redis images/config/volumes не обновлять.

До cutover заполнить evidence record (секреты не включать):

| Обязательный identity | Что сохранить / проверить |
| --- | --- |
| Source | exact target SHA, signed/reviewed commit relationship, manifest SHA256, source hashes 221 files; migration chain `0011 → 0012` |
| Candidate image | реальный `sha256:` image ID + platform; registry `repo@sha256:` если есть; exported archive SHA256 для offline load; build source identity/OCI revision и package fingerprint |
| Builder | isolated exact Git export, reviewed Dockerfile/context, base image digest, installed package inventory. Dockerfile и requirements не pinned полностью: повторный build не обязан дать тот же image |
| Runtime attestation | source hashes внутри **реального** candidate image, ownership/modes root:root/no unsafe write/setid, no symlink ancestors; package inventory; entrypoint/command; no code-masking mounts; fixed/graph readiness |
| Rollback | фактические image IDs/digests **для каждого** worker/backend/bot, source/package/config hashes, retained local image availability/archive checksum; tag сам по себе недостаточен |
| Persistence | exact DB identity/volume ID/mounts, media volume IDs/mounts, protected backup + separately verified restore procedure/RPO, baseline counts/read access; не откатывать живой DB к старому snapshot ради приложения |
| Runtime configuration | fingerprints .env + effective container/Compose config + overrides/restart/networks/mounts. Секреты и значения env не выводить; models/budgets/provider settings/projection flags не менять |

**На этой стадии candidate/rollback image IDs отсутствуют, их нельзя выдумать.**
Local Docker unavailable; CI image build success не attests production image.
Сборка допустима позже в изолированной локальной/CI среде после review контекста;
production build здесь запрещён. Устанавливать по immutable ID, `--pull never`,
`--no-build`, `--no-deps` с reviewed Compose override, где image заменён, build
отсутствует. Все фактические `-f` файлы и project name из inventory, не guessed
`docker compose up --build`/`pull`/`up` всего проекта. Не запускать migrate через
implicit depends_on. Не включать CI fake-provider overlay в production.

Build context брать только из pinned Git export с LF (`git -c core.autocrlf=false
-c core.eol=lf archive`), не из текущего checkout: существующий `.dockerignore`
не исключает все возможные вложенные worktrees/evidence. В context не должны
попасть `.env`, локальные test stores, credentials или untracked artifacts.

## 6. PostgreSQL roles и migration gate

Миграция additive и создаёт open row epoch 0. Она применяется **после** legacy
drain/stop и **до** любого нового worker. На первом bootstrap `status` до 0012
может только отказать; это не ошибка для обхода.

Использовать существующие approved role-management средства/DB administrator,
не создавать SSH access infrastructure. Separate migration owner, application
runtime role и protected operator role. Перед cutover проверить effective grants,
role membership/ownership/SET ROLE escalation, superuser/CREATEROLE/BYPASSRLS и
отсутствие неутверждённых writers. Нынешний Compose может использовать database
owner как runtime role; это **не** доказательство least privilege.
Не отзывать grants вслепую: role changes — отдельная reviewed часть cutover.

Минимальные effective privileges для новых tables:

| Role | Необходимые privileges |
| --- | --- |
| Workers | `SELECT` + `UPDATE(id)` на worker_admission (нужен row lock), без `UPDATE(paused,epoch)`; worker_attempts `SELECT(job_id,claim_token)`, INSERT, DELETE; существующие job/run/artifact grants сохраняются |
| Operator | worker_admission `SELECT(id,paused,epoch)`, `UPDATE(id,paused,epoch)`; jobs `SELECT(job_id,kind,status)`; job_executions `SELECT(job_id,claim_token,lease_until,available_at)`; worker_attempts `SELECT(job_id,claim_token)`; schema USAGE/DB CONNECT; без payload read и worker-table DML |
| Migration owner | DDL, отдельно от worker и operator; доступ только на согласованное окно |

`WORKER_DRAIN_DATABASE_URL` обязателен с `postgresql+asyncpg`, без fallback на
`DATABASE_URL`. Не помещать DSN в CLI args/history/PR/output. Operator probe
проверяет grants read-only; отсутствие row-lock error в реальном live CLI после
0012 дополнительно подтверждает применимость grants. Базовая role проверяется
также в local disposable restricted-role tests. Collector не выдаёт PASS по одним
booleans: ownership/role escalation требует DBA review.

## 7. Операторская последовательность cutover (пока не разрешена)

Каждый шаг требует успешного предыдущего. Команды ниже — reviewed CLI primitives,
не исполнимый installer; approved exact image IDs/project/overrides/process list и
timeouts будут вписаны после reconnaissance. Владелец window сохраняет evidence
с server timestamp, phase, image/process/DB identity и epoch, не ручной `verified=true`.

1. **Preflight.** Заполнить inventory/provenance/role/backup gates выше; отдельный
   reviewer принимает bootstrap и Telegram recovery; получить разрешение на
   конкретный maintenance plan. Непосредственно перед window повторить collector,
   сверить identities. Все фоновые deploy/resume/restart действия исключены.
2. **External producer barrier → accepted requests complete.** Применить §4 ко
   всем API/bot/direct writers. Зафиксировать closed listeners, held restart
   и graceful API completion; не заменять это idle snapshots.
3. **Legacy drain.** Старые workers пока работают. Повторять read-only DB aggregate
   probe против authoritative DB всех workers. Требовать одновременно:
   `unfinished_jobs=deferred_jobs=current_tokens=active_leases=expired_tokens=0`,
   `metadata_anomalies=orphan_executions=graph_plan_anomalies=0`,
   `unknown_unfinished_kinds=0`, `active_runs=0`. У legacy **вся** очередь должна
   закончиться, включая future retries и graph descendants. Fixed runs в
   `needs_input`/`awaiting_*` не queued/running и могут сохраниться; graph с
   queued/running и нулём jobs — STOP, не пустая очередь. Если 0012 уже существует,
   любые attempt markers тоже должны быть 0 и причина частичного rollout разобрана.
   Сохранить повторные snapshots вместе с неизменными producer/worker identities.
4. **Legacy execution proof.** Старые binaries не имеют attempt markers: expired
   или superseded provider calls могли исчезнуть из current token. Нулевая DB
   очередь **не доказывает** отсутствие таких calls. Нужны независимые сведения
   всех legacy in-flight attempts/корректное unwind, включая superseded calls,
   либо заранее validated runtime upper-bound + non-cancellation completion
   observation на каждом процессе. `lease_until`, ожидание 330 секунд или
   отсутствие логов не заменяют proof. Если legacy telemetry/accounting этого не
   позволяет доказать — **NO-GO, retain legacy workers**; force stop запрещён.
5. **Остановить idle legacy workers.** Ещё раз live legacy gates и closure producer
   barrier; только после них graceful TERM с held restart, без active I/O. Подтвердить
   все PID/start identities исчезли, containers не restarting, альтернативных
   executors/supervisors нет. Сохранить DB/Redis/media. Не начинать migration при
   живом legacy worker. При неожиданном restart — STOP и повторная проверка.
6. **Migration 0012.** От target immutable image запустить ровно one-shot migrate
   с `alembic upgrade 20261014_0012`, без worker/backend dependencies и provider
   network. Только approved migration credentials. Require exit 0, read-only head
   ровно `20261014_0012`, `alembic check` без operations (это schema inspection,
   не autogenerate/apply). Не редактировать merged revisions, не `stamp head`.
7. **Установить paused admission.** Новые workers всё ещё не запущены. Dedicated
   protected operator environment, target CLI:

   ```bash
   python -m app.worker_control status
   python -m app.worker_control pause --expect-epoch N
   python -m app.worker_control status --require-drained --expect-epoch E
   ```

   N берётся из живого status, E из успешного committed pause. Проверить JSON
   schema `worker_drain.v1`, admission `paused`, epoch E, drained true,
   оба `outstanding_attempts=active_leases=0`. Nonzero = STOP. При потерянном
   acknowledgement перечитать status и согласовать epoch; не угадывать N/E.
8. **Старт target workers paused.** Exact immutable image и прежняя configuration,
   no-build/no-pull/no-deps; проверить фактический image ID, source/package/mode
   fingerprints, mounts/networks и absence legacy processes. Проверить обе lane
   families и registry 1.3.0 через bounded startup evidence, не создавать smoke
   jobs. Readiness message до DB claim не доказывает drain. После каждого старта
   **заново вызвать live** CLI `status --require-drained --expect-epoch E`; CLI
   exit 0 и zero outstanding/leases обязательны. Старый JSON не принимается.
9. **Structural verification paused.** Повторить head/grants/same-DB/source/config/
   volumes/image identities и отсутствие crash/restarts/cleanup errors. У нового
   worker no missing-row/control errors. Backend/bot остаются выключены, если нет
   доказанной ingress isolation для pre-resume startup. Никаких диагностических
   OpenAI POST, model/budget/provider/projection изменений и force-clear metadata.
10. **Resume.** Последний live gate на E, затем
    `python -m app.worker_control resume --expect-epoch E`; подтвердить open и
    возвращённый epoch. Сохранить evidence. Не доверять exit 0 без JSON state.
11. **Снять ingress barrier.** Только после resume запустить attested compatible
    backend, выполнить GET `/health`, `/ready`; затем bot и прочие writers,
    восстановить approved restart policies. Если existing network barrier
    позволял старт backend раньше, снять его теперь после тех же проверок.
    Порядок сохраняет `resume → ingress open`; нового producer до resume нет.
12. **Postflight.** Повторить sanitized inventory и read-only DB/status, schema
    head, source/image/config fingerprints, both lanes/no restart loops и
    volumes. Read-only workflow/Copilot status/list с owner auth — допустимый
    smoke, не execute. Delivery backlog допускается и не force-cleared.
    Telemetry #122 структурно подтверждена source + offline tests; если после
    разрешённого resume естественный трафик отсутствует, production telemetry
    pairs имеют статус **NOT_OBSERVED**, не PASS. Новые model calls ради проверки
    telemetry в этот plan не входят.

Reusable future control-aware updates допускают pending/deferred jobs при live
drain: это отличается от **полного legacy drain** в шагах 3–4. Даже новая CLI
`drained=true` не доказывает наличие всех workers в одном DB, отсутствие legacy
executors, structural correctness или active leases — эти gates проверяются отдельно.

## 8. STOP, emergency recovery, rollback

STOP/NO-GO при неизвестном ingress/writer/worker, несовпадении DB/source/image/
config/schema, невозможности завершить accepted handlers, unsafe Telegram replay,
unknown legacy superseded call, stale epoch, concurrent operator resume, missing
role/grants/control row, expired token/retained marker, metadata anomaly, DB outage,
частичной migration, crash/OOM/restart или нарушении budget/model/config invariant.
Waiting window/timeouts утверждаются до начала (например, 15 минут на операционный
шаг с продлением только по отдельному решению); deadline означает HOLD/STOP,
никогда SIGKILL или автоматическое снятие barrier.

| Точка отказа | Безопасное действие |
| --- | --- |
| До остановки legacy | Не менять DB; удержать closure, расследовать; после доказанного завершения принятых producers можно отдельно согласовать abort maintenance и вернуть прежний ingress |
| После legacy stop, до migration | Держать ingress closed; перепроверить legacy idle/provenance и по approved abort plan вернуть прежние workers; paused row ещё не является защитой |
| Migration/ack uncertain | Не стартовать workers. Прочитать schema/head/status, согласовать с DBA. Не stamp/downgrade/drop/retry blindly |
| Target не стартует paused | Сохранить pause E и producer barrier. Исправить reviewed config или выбрать attested compatible image; не открывать admission ради диагностики |
| DB outage / retained markers | Держать barrier/pause; восстановить DB availability. Нельзя удалять markers/tokens/leases/jobs или менять attempts/availability, чтобы пройти gate; отдельное recovery с независимым proof необходимо |
| Post-resume incident | Снова закрыть все producer ingress и завершить accepted requests; затем pause/drain по live E для control-aware executors. Не обрывать provider I/O |

**Control-aware rollback:** повторить producer barrier при необходимости смены
producers, pause → live drain at captured E → stop idle target workers → restore
attested control-aware image → structural/live E gates → explicit resume → reopen.
Оставить DB на 0012 и существующие volumes/artifacts/configuration.

**Legacy rollback:** старый worker игнорирует admission. **Возвращать его только
под повторно установленным external barrier**. Если ingress уже открывался:
close → accepted-request completion → pause новых workers → live drain; при
pending/deferred jobs одного paused drain недостаточно. Под закрытым ingress
контролируемо resume совместимые новые workers и дождаться полного backlog/graph
drain, затем pause/live zero gate и stop всех target workers. Проверить отсутствие
всех outstanding/superseded calls и compatibility старого image с нынешней schema/
retained data. Только затем restore legacy worker с ingress closed; он начнёт
claims независимо от paused row. Держать barrier до нового решения об open.
Если полный drain/совместимость недоказуемы — rollback legacy **NO-GO**, сохранять
paused target и восстанавливать вперёд. Если ingress никогда не открывался,
повторно проверить, что первоначальный barrier всё ещё реально действует.

Не downgrade 0012 ради worker rollback, не восстанавливать старый DB snapshot
поверх новых данных, не `down --volumes`, не purge Redis, не переключать model/
budgets/provider credentials для smoke. Отдельное DB disaster recovery — отдельный
approved incident plan, не shortcut этого rollout.

## 9. Что нужно для решения GO

Независимый reviewer должен получить: sanitized reconnaissance с объяснением всех
listeners/processes/writers/Compose overrides; proof bootstrap closure + accepted
completion + Telegram recovery; legacy full drain и proof отсутствия superseded I/O;
attested candidate и rollback identities; production schema/grants/DB/volume/backup
evidence; успешный локальный runtime barrier rehearsal на фактических версиях и
отдельное разрешение на конкретный cutover. Сейчас эти production gates не выполнены.

**Итог подготовки: NO-GO для production rollout; пакет передаётся на независимое
ревью. Никакие production commands из документа пока не исполнять.**
