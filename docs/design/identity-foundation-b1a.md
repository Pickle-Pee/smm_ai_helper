# B1a — фундамент единой идентичности (Telegram + будущий Web)

Статус: **Draft, merge заблокирован до интеграции стека PR #174 в `master` (D17 / OQ-5)**.
Задача: [#202](https://github.com/Pickle-Pee/smm_ai_helper/issues/202), родитель [#160](https://github.com/Pickle-Pee/smm_ai_helper/issues/160), эпик [#158](https://github.com/Pickle-Pee/smm_ai_helper/issues/158).
Контракт: [Brenvio Web API v2 C0](https://github.com/Pickle-Pee/smm_ai_helper_web/blob/main/docs/api/README.md) §§5.3, 6; [Decision Register](https://github.com/Pickle-Pee/smm_ai_helper_web/blob/main/docs/api/decision-register.md) D2, D9, D17, OQ-5, OQ-7, OQ-12.

B1a — изменение только слоя данных. Web-логина, сессий, CSRF, email/OIDC, организаций, проектов и `/v2` маршрутов нет.
Поведение бота, `require_bot`/`require_actor`, Copilot, workflow/orchestrator, Quality Gates и provider calls не меняются.

## 1. Точка интеграции и Alembic

| Факт (проверено 2026-11-14) | Значение |
|---|---|
| `origin/master` | `76b6c1b`, Alembic head `20261026_0013` |
| `origin/sale-ready` | `b231567`, head `20260917_0009`; полностью содержится в `master` (0 своих коммитов, отстаёт на 133). Указание в `AGENTS.md` устарело; фактическая integration-ветка — `master` (D9) |
| PR #174 | открыт, Draft, head `100bff1`, стек из 35 PR (#139 → #174) поверх `master`; единственная новая миграция стека — `20261103_0014` (revision `20261103_0014`, down `20261026_0013`) |
| Production | по журналу приёмки работает на `20261103_0014` (релиз e99); приёмка #174 не завершена |
| Другие открытые PR с миграциями | нет новых ревизий (только `env.py` / уже существующая `0013`) |

Production уже стоит на `20261103_0014`. Поэтому любая ревизия B1a с `down_revision = 20261026_0013` создала бы вторую голову относительно production.
Единственная корректная цепочка: `0013 → 0014 (#174) → 0015 (B1a)`.

- Новая ревизия: `20261114_0015` (`migrations/versions/20261114_0015_external_identities.py`), `down_revision = "20261103_0014"`.
- Ветка `codex/saas-b1-identity-foundation` создана от `100bff1` (head PR #174) без изменения ветки #174. Draft PR стекуется на неё.
- **Блокировка:** до merge стека #174 в `master` (или до объявления владельцем другой integration-головы, OQ-5) B1a не мержится и не деплоится.
  Если #174 будет переписан (rebase/squash), B1a нужно перебазировать. Ревизия `20261103_0014` уже применена в production, поэтому её id меняться не должен.

## 2. Старая модель

```
Telegram update ─► bot ─► HTTP (Bearer BOT_BACKEND_TOKEN + X-Telegram-User-ID)
                              │ require_bot / require_actor
                              ▼
          users.telegram_id (NOT NULL, UNIQUE) ─► users.id ─► AI Core (tasks, runs, jobs, brand_profiles, …)
```

- `users.id` — внутренний principal; все FK владения ссылаются на него.
- `users.telegram_id` — `BIGINT NOT NULL`, `users_telegram_id_key` UNIQUE + `ix_users_telegram_id` UNIQUE.
- Пользователь создаётся неявно при первом запросе актора: `INSERT … ON CONFLICT (telegram_id) DO NOTHING`, либо ORM в `UserService.get_or_create`.

### Матрица совместимости (по коду `100bff1`)

| Место | Что предполагает | После B1a |
|---|---|---|
| `app/security.py` `require_bot`, `require_actor` | bot token + числовой actor `0 < id < 2^63` | без изменений; `external_identities` не используется для авторизации |
| `authorize_legacy_request` (`security.py:54`) | `Task ⋈ User WHERE telegram_id = actor` | без изменений; NULL никогда не совпадает с actor |
| Создание пользователя по actor: `marketing_copilot/api_service.py:51`, `workflows/service.py:51`, `chat_memory_service.py:38`, `chat_execution_service.py:72,80`, `project_context_service.py:154`, `UserService.get_or_create` | создаёт строку `users` с реальным Telegram ID | код не меняется; trigger `users_mirror_telegram_identity` в той же транзакции создаёт identity; ветка `ON CONFLICT DO NOTHING` trigger не вызывает |
| Поиск владельца по actor: `run_reader.py`, `mentor.py:209`, `workflows/service.py:56,172`, `project_context_service.py`, `project_history_service.py`, `chat_memory_service.py:34`, `task_history_service.py`, `task_result_service.py`, `task_completion_service.py`, `brand_profile_service.py` | `User.telegram_id == actor` | без изменений; web-only пользователь (NULL) не находится ни одним из запросов |
| Обратный поиск owner → telegram_id: `marketing_copilot/execution_store.py:79` | владелец Copilot всегда Telegram-пользователь | в B1a верно: owner берётся из `_identity_context(actor)`. **B3+ (tenant-scoped Copilot) не должен вызывать это с web-only owner** |
| `workflows/delivery.py:34` | владелец запуска имеет `telegram_id` | уже fail-closed: `None` → «Delivery owner missing», без отправки |
| `workflows/executors.py:120` | `snapshot["telegram_id"]`, записанный при создании запуска | не зависит от `users` |
| `conversations.user_id`/`messages.user_id` (`tg:<id>`), `task_sessions.user_id` (`str(id)`), `active_project_bindings.actor_id`, `project_discussion_turns.actor_id` | строковые/числовые actor-ключи без FK на `users` | не переписываются |
| FK на `users.id`: `tasks`, `brand_profiles` (UNIQUE), `marketing_runs`, `jobs` (CASCADE), `owned_product_snapshots`, `copilot_interpretations`, `project_sessions`, `active_project_bindings` | стабильный `users.id` | `users.id` не меняется; строки не трогаются |
| `app/schemas.py` `UserCreate.telegram_id: int` | DTO payload бота | без изменений; бот всегда передаёт реальный id. `UserRead` нигде не используется |
| Удаление пользователя (очистка в тестах, операторские процедуры) | — | identities удаляются каскадом (`ON DELETE CASCADE`) |

## 3. Новая модель

```
                 users.id (PK, единственный principal)
                         │ 1
                         │ *
                 external_identities
              (provider, subject) UNIQUE
                /                  \
     telegram (B1a, активно)    email / oidc:<issuer> (зарезервировано, не создаётся)
             │
   существующий бот без изменений
```

### `users`

- `telegram_id` → **nullable**. Уникальность ненулевых значений сохраняется: `users_telegram_id_key` и `ix_users_telegram_id`. Несколько NULL допустимы.
- Новый `uq_users_id_telegram_id UNIQUE (id, telegram_id)`. Это цель составного FK; новой семантики у него нет.
- `users.telegram_id` **неизменяем** (trigger `users_telegram_id_immutable`, SQLSTATE `23001 restrict_violation`). Запрещены X→Y, X→NULL и NULL→X.
  Привязка Telegram к существующему web-only пользователю и merge аккаунтов в B1a невозможны даже по ошибке в коде.

### `external_identities`

| Колонка | Тип | Назначение |
|---|---|---|
| `id` | `INTEGER` PK | суррогатный ключ |
| `user_id` | `INTEGER NOT NULL` FK `users.id ON DELETE CASCADE` | владелец |
| `provider` | `VARCHAR(64) NOT NULL` | `telegram`; зарезервированы `email` и `oidc:<issuer-key>` (C0 §5.3) |
| `subject` | `VARCHAR(255) NOT NULL` | канонический идентификатор у провайдера; для Telegram — точный десятичный ID |
| `telegram_id` | `BIGINT NULL` | якорь согласованности: только для `telegram`, равен `subject` |
| `verified_at` | `TIMESTAMPTZ NOT NULL` | когда идентичность была подтверждена; в таблице только подтверждённые identities |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | когда строка создана (`linked_at` в C0 `Identity`) |

Ограничения:

- `uq_external_identities_provider_subject UNIQUE (provider, subject)` — одна внешняя идентичность принадлежит ровно одному пользователю; этот же индекс служит для поиска.
- `ix_external_identities_user_id` — поиск по пользователю.
- `fk_external_identities_user_telegram (user_id, telegram_id) → users (id, telegram_id) ON DELETE CASCADE` (`NO ACTION` на update). Telegram identity может ссылаться только на пользователя, которому этот Telegram ID принадлежит. Строку нельзя перевесить на другого пользователя или оставить при смене `users.telegram_id`.
- `ck_external_identities_provider` — `telegram | email | oidc:[a-z0-9][a-z0-9._-]{0,58}`.
- `ck_external_identities_subject`:
  - для `telegram`: `telegram_id > 0` и `subject = telegram_id::text` (без ведущих нулей и знака);
  - для остальных провайдеров: `telegram_id IS NULL`, а subject непустой и без пробелов по краям.

Почему identity создаётся trigger'ом, а не кодом сервисов: Telegram-пользователи создаются в 7 местах ядра (Copilot, workflow, chat, project context). Правка всех этих мест — рефакторинг AI Core и конфликты с активным стеком #174. `AFTER INSERT` trigger атомарен с созданием пользователя и покрывает все пути, включая будущие. Код ядра при этом не меняется.

Почему без ORM relationship: у таблицы два FK на `users`, а навигация из ядра не нужна. `User` mapper не меняется, кроме nullability колонки.

## 4. Правила связки идентичностей (B1a)

1. Единственный внутренний идентификатор — `users.id`. Identity никогда не является principal.
2. Telegram identity создаёт только PostgreSQL: backfill миграции и trigger при `INSERT INTO users` с реальным `telegram_id`. Telegram ID приходит только через аутентифицированную границу бота (`require_actor`).
3. Одна `(provider, subject)` — один пользователь. Повторная привязка, перенос и «угон» отклоняются ограничениями БД, а не проверками в приложении.
4. Пользователь может иметь несколько identities разных провайдеров. Схема и тесты это поддерживают; создание email/OIDC в B1a не реализовано.
5. Фиктивных Telegram ID нет: web-only пользователь — `telegram_id IS NULL` без Telegram identity.
6. Неявного объединения аккаунтов нет. `IdentityService.resolve_*` только читает; создающих или связывающих API нет.

## 5. Миграция и backfill

`upgrade()` выполняется одной транзакцией (Alembic `begin_transaction`):

1. Preflight: если есть `users.telegram_id <= 0`, миграция прерывается с `RuntimeError` и ничего не меняет.
2. `ALTER users.telegram_id DROP NOT NULL`, затем `ADD uq_users_id_telegram_id`. `ALTER` берёт `ACCESS EXCLUSIVE` на `users` до commit, поэтому параллельная вставка пользователя между backfill и trigger невозможна. Таблица маленькая, блокировка короткая. Rollout всё равно делается по стандартной процедуре: пауза, drain, additive migration, resume.
3. `CREATE TABLE external_identities` с ограничениями и индексом; создание двух trigger-функций и trigger'ов.
4. Backfill: `INSERT … SELECT id, 'telegram', telegram_id::text, telegram_id, created_at AT TIME ZONE 'UTC', now() FROM users WHERE telegram_id IS NOT NULL ON CONFLICT (provider, subject) DO NOTHING`.
   `verified_at` равен `users.created_at` (UTC): это первый момент, когда бот увидел аутентифицированного Telegram-актора.
5. Проверка: если остался хоть один Telegram-пользователь без собственной identity (`user_id = id` и `telegram_id = telegram_id`), `RuntimeError` откатывает всю миграцию.

Гарантии: `users.id`, `users.telegram_id`, tasks, история, `brand_profiles`, `marketing_runs.user_id`, jobs, receipts и orchestration state не читаются на запись и не изменяются.
Повторное применение (downgrade → upgrade) и повторный ремонт идемпотентны. Если существующая привязка указывает на другого пользователя, `ON CONFLICT` ничего не переписывает, а проверка завершается ошибкой.

### Ремонт и проверка после деплоя

`IdentityService.backfill_telegram_identities(session)` повторяет backfill. Транзакцией владеет вызывающий. Сервис возвращает `TelegramBackfillReport(telegram_users, created)`; при рассогласовании бросает `IdentityConflictError`, и вызывающий делает rollback.
Read-only проверка (должна вернуть 0):

```sql
SELECT count(*) FROM users u
WHERE u.telegram_id IS NOT NULL AND NOT EXISTS (
  SELECT 1 FROM external_identities e
  WHERE e.provider = 'telegram' AND e.user_id = u.id AND e.telegram_id = u.telegram_id);
```

## 6. Откат

- `downgrade()` (`0015 → 0014`) отказывается работать (`RuntimeError`, транзакция откатывается), если есть пользователи с `telegram_id IS NULL` или не-Telegram identities: восстановление `NOT NULL` или удаление таблицы потеряли бы данные. Сначала их нужно явно мигрировать; удалять пользователей автоматически нельзя.
- В остальных случаях удаляются trigger'ы, функции, `external_identities` и `uq_users_id_telegram_id`, а `telegram_id` снова становится `NOT NULL`. Telegram identities полностью выводятся из `users.telegram_id`. Теряются только метаданные `verified_at`/`created_at`; повторный upgrade восстанавливает строки.
- Откат приложения без отката схемы безопасен. Старый код не знает о таблице; trigger продолжает создавать identities; старый код не обновляет `telegram_id`.
- На общих БД downgrade не выполняется; тестовые downgrade — только на disposable `smm_mvp_test*`.

## 7. Безопасность

| Проверка | Механизм | Доказательство (тест) |
|---|---|---|
| Уникальность identity | `UNIQUE (provider, subject)` | `test_telegram_id_and_provider_subject_are_unique`, `test_concurrent_first_requests_and_bindings_resolve_atomically` |
| Изоляция владельцев | составной FK + CHECK + immutable `telegram_id` | `test_a_telegram_identity_cannot_be_bound_to_another_user_or_relinked` |
| Безопасность миграции | backfill только `INSERT`, проверка, одна транзакция | `test_upgrade_backfills_legacy_users_without_touching_ownership`, `test_upgrade_aborts_atomically_on_a_non_canonical_legacy_telegram_id` |
| NULL Telegram ID | nullable + отсутствие совпадений в `== actor` | `test_web_only_user_has_null_telegram_id_and_does_not_disturb_telegram_queries` |
| Legacy-авторизация | `require_bot` не изменён; identity ничего не даёт без bot token | `test_legacy_bot_endpoints_keep_their_owner_and_still_require_the_bot_token`, существующий `tests/test_http_security.py` |
| Конфликты не переназначаются | `IdentityConflictError` + rollback | `test_backfill_conflict_fails_visibly_and_rolls_back_without_reassignment` |
| Секреты в браузере | в B1a нет фронтенда, новых env и маршрутов | diff PR |

Тесты не делают внешних AI-вызовов (`OPENAI_BASE_URL` указывает на недоступный адрес) и не обращаются к Telegram и production.

## 8. План B2 (не реализуется здесь)

1. Telegram Login exchange (одноразовая ссылка из бота, `auth_tokens`, хранится только hash) → сессия на `users.id`, найденном через `IdentityService.resolve_telegram_user_id` по уже существующей Telegram identity. Пользователей и identities B2 не создаёт.
2. `web_sessions` (hash токена, `expires_at`, `revoked_at`), cookie `HttpOnly; Secure; SameSite`, CSRF по C0 §5.2, флаг по умолчанию выключен.
3. Web-маршруты — отдельная зависимость аутентификации. `require_actor`/`X-Telegram-User-ID` браузеру не принимаются никогда.
4. Email (B2e) и OIDC: отдельные миграции. В них правила канонизации subject (регистр email, issuer key OIDC), отдельная таблица непроверенных challenges и решение о привязке/merge (политика владельца).
5. Перед tenant-scoped Copilot (B3+) нужно убрать предположение `execution_store.py:79` о Telegram-владельце.

## 9. Нерешённые вопросы (решения не принимаются в B1a)

- **D17 / OQ-5** — порядок миграций и integration-голова. B1a построен на фактической production-голове `20261103_0014`, но мержится только после стека #174 или объявленной владельцем головы.
- **OQ-12** — источник `display_name` (новая колонка либо `first_name`/`username`). B1a колонку не добавляет и `users` кроме nullability не меняет.
- **OQ-7** — сроки жизни сессий (idle/absolute) для B2. В B1a сессий нет.
- Политика автоматической привязки и merge аккаунтов (C0 §5.3). В B1a технически запрещена; решение за владельцем продукта.
- Полное разрешение `email` и `oidc:*` в CHECK — соответствует C0 §5.3. Если владелец предпочтёт разрешать провайдеров только вместе с их B2e/B6-миграциями, CHECK сужается до `telegram` без изменения данных.
