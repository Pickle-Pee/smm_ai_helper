# B2 — аутентификация и web-сессии (подготовка)

Статус: **Draft. Подготовка начата 17.11.2026; код и миграция не написаны. Merge — только после B1a.**
База: ветка `codex/b1a-identity-on-ai-core-1.0` (B1a поверх релизного кандидата AI Core 1.0, PR #216).
Контракт: [Brenvio Web API v2 C0](https://github.com/Pickle-Pee/smm_ai_helper_web/blob/main/docs/api/README.md) §§4, 5, 9;
[Decision Register](https://github.com/Pickle-Pee/smm_ai_helper_web/blob/main/docs/api/decision-register.md) D1, D2, D4, C0-10, C0-23, OQ-6, OQ-7.
Предшественник: `docs/design/identity-foundation-b1a.md` §8 (план B2).

B2 даёт браузеру способ войти и держать сессию на **том же `users.id`**, что использует бот.
Организаций, проектов, `/v2` ресурсов Copilot, email/OIDC и merge аккаунтов в B2 нет (B3–B6, B2e).
AI Core 1.0 (Expert Core, Orchestrator, Quality Gates, durable verification, receipts, delivery) B2 не затрагивает.

## 1. Объём B2

| Входит | Не входит |
|---|---|
| `POST /internal/identity/web-login-link` (bot trust zone) | personal-организация и проект при первом входе (B3) |
| `POST /v2/auth/telegram/exchange` → `AuthSession` + cookie | `/v2/orgs`, `/v2/projects`, бренды (B3, B4) |
| `GET /v2/auth/csrf`, `POST /v2/auth/logout`, `GET /v2/me` | Copilot через `/v2` (B5/B6) |
| таблицы `auth_tokens`, `web_sessions` (миграция `20261118_0016`) | email magic link / OTP (B2e), OIDC, привязка Telegram к web-only |
| зависимость `require_web_session` и CSRF-проверка | rate limiting общего вида и квоты генераций (OQ-6, B5) |
| кнопка «Открыть Brenvio» в боте | UI (репозиторий `smm_ai_helper_web`, F2) |

`GET /v2/me` минимален: `User` без Telegram ID (C0 §4). Без него браузер не может проверить сессию.

## 2. Поток входа

1. Пользователь нажимает в боте «Открыть Brenvio». Бот вызывает `POST /internal/identity/web-login-link` с bot token и `X-Telegram-User-ID` (существующий `require_actor`; маршрут не публикуется через edge).
2. Backend находит `users.id` через `IdentityService.resolve_telegram_user_id(actor)`. B2 не создаёт ни пользователей, ни identities: если строки нет, ответ `409 telegram_identity_required` (на практике её создаёт первый запрос бота).
3. Создаётся строка `auth_tokens`: 256 бит из `secrets.token_urlsafe(32)`, в БД только `sha256`, `purpose='telegram_web_login'`, TTL 10 минут. Ответ: `{"url": "<WEB_APP_ORIGIN>/auth/telegram#t=<token>", "expires_at": …}`.
4. UI отправляет `POST /v2/auth/telegram/exchange {token}`. Одним SQL-оператором токен погашается:
   `UPDATE auth_tokens SET consumed_at = now() WHERE token_hash = :h AND purpose = 'telegram_web_login' AND consumed_at IS NULL AND expires_at > now() RETURNING user_id`.
   В той же транзакции создаётся `web_sessions`. Неизвестный, истёкший и погашенный токен неразличимы: `401 login_token_invalid`.
5. Ответ `200 AuthSession {user, csrf_token, expires_at}` и `Set-Cookie: __Host-brenvio_session=<256 бит>; HttpOnly; Secure; SameSite=Lax; Path=/` без `Domain`.

Повтор exchange тем же токеном при сетевом сбое не создаёт вторую сессию: токен уже погашен, ответ `401`, пользователь запрашивает новую ссылку. Exactly-once для сессии не обещается и не нужен.

## 3. Схема (миграция `20261118_0016_web_auth`, `down_revision = "20261114_0015"`)

Только expand. Существующие таблицы не меняются.

`auth_tokens`

| Колонка | Тип | |
|---|---|---|
| `id` | `BIGINT` PK | |
| `user_id` | `INTEGER NOT NULL` FK `users.id ON DELETE CASCADE` | |
| `purpose` | `VARCHAR(32) NOT NULL` | CHECK `purpose = 'telegram_web_login'` (расширяется в B2e) |
| `token_hash` | `CHAR(64) NOT NULL UNIQUE` | hex `sha256` |
| `created_at`, `expires_at` | `TIMESTAMPTZ NOT NULL` | CHECK `expires_at > created_at` |
| `consumed_at` | `TIMESTAMPTZ NULL` | |

Индекс `ix_auth_tokens_user_created (user_id, created_at)` — для лимита выдачи ссылок.

`web_sessions`

| Колонка | Тип | |
|---|---|---|
| `id` | `BIGINT` PK | наружу не отдаётся |
| `user_id` | `INTEGER NOT NULL` FK `users.id ON DELETE CASCADE` | |
| `token_hash` | `CHAR(64) NOT NULL UNIQUE` | `sha256` cookie |
| `csrf_hash` | `CHAR(64) NOT NULL` | `sha256` CSRF-токена сессии |
| `created_at`, `last_seen_at` | `TIMESTAMPTZ NOT NULL` | |
| `idle_expires_at`, `absolute_expires_at` | `TIMESTAMPTZ NOT NULL` | CHECK `idle_expires_at <= absolute_expires_at` |
| `revoked_at` | `TIMESTAMPTZ NULL` | |

Индекс `ix_web_sessions_user (user_id) WHERE revoked_at IS NULL`.

CSRF хранится как хэш случайного токена, без нового серверного секрета (C0-10). Новых секретов в env B2 не добавляет.

Откат: `downgrade()` удаляет обе таблицы. Последствие — все web-сессии теряются, бот не затронут. На общих БД downgrade не выполняется.

## 4. Слой сервисов и HTTP

- `app/services/web_auth_service.py` — `issue_login_link`, `exchange`, `resolve_session`, `rotate_csrf`, `revoke`. Транзакцией владеет вызывающий, как в `IdentityService`.
- `app/security_web.py` — зависимость `require_web_session(request) -> WebPrincipal(user_id, session_id)`:
  - читает только cookie `__Host-brenvio_session`;
  - отклоняет запрос, если в нём есть `Authorization: Bearer <BOT_BACKEND_TOKEN>` или `X-Telegram-User-ID` (C0 §4: bot-учётные данные в web-зоне не принимаются);
  - для `POST/PATCH/DELETE` проверяет `X-CSRF-Token` (сравнение хэшей через `compare_digest`) и same-origin: `Origin == WEB_APP_ORIGIN` или `Sec-Fetch-Site: same-origin`;
  - продлевает idle-срок не чаще раза в 5 минут (одно `UPDATE … WHERE last_seen_at < now() - 5 min`), чтобы чтение не писало в БД на каждый запрос.
- `app/routers/web_auth.py` — тонкий роутер `/v2/auth/*` и `/v2/me`. Ответы — allowlist-DTO, ошибки — `ErrorResponse` (`unauthenticated`, `login_token_invalid`, `csrf_failed`, `feature_disabled`, `rate_limited`), `Cache-Control: private, no-store` на всех ответах (C0-23).
- `app/routers/identity_internal.py` — `POST /internal/identity/web-login-link` под `require_actor`.
- Бот: кнопка «Открыть Brenvio» в меню; отправляет ссылку только в личный чат. Хендлер тонкий: вызов backend и рендер.

Существующие `require_bot`/`require_actor`, legacy-маршруты, `/copilot/*` и durable delivery не меняются. `/v2` никогда не принимает bot-токен; legacy-маршруты никогда не принимают web-сессию.

## 5. Конфигурация

| Настройка | По умолчанию | Назначение |
|---|---|---|
| `WEB_AUTH_ENABLED` | `false` | при `false` все `/v2/auth/*` и `/internal/identity/web-login-link` отвечают `403 feature_disabled`, кнопка в боте скрыта |
| `WEB_APP_ORIGIN` | пусто | `https://app.<domain>`; обязателен при `WEB_AUTH_ENABLED=true`, проверяется при старте |
| `WEB_SESSION_IDLE_SECONDS` / `WEB_SESSION_ABSOLUTE_SECONDS` | 7 / 30 дней | OQ-7, решение владельца |
| `WEB_LOGIN_LINK_TTL_SECONDS` | 600 | C0 §5.1 |
| `WEB_LOGIN_LINKS_PER_10_MIN` | 5 | лимит выдачи на пользователя по `auth_tokens`; общие лимиты — OQ-6 |

## 6. Модель угроз

| Угроза | Защита | Тест |
|---|---|---|
| Кража токена из логов прокси или `Referer` | токен во фрагменте URL; страница сразу убирает его; TTL 10 мин; одноразовость | интеграционный тест exchange; проверка отсутствия токена в логах приложения |
| Повторное использование ссылки | атомарное погашение одним `UPDATE … RETURNING` | параллельные exchange одного токена → ровно одна сессия |
| Вход за другого пользователя | ссылка выдаётся только для `require_actor`; `user_id` берётся из identity, а не из запроса | тест: actor A не может получить ссылку для B |
| Утечка БД | в БД только `sha256` токенов, сессий и CSRF | тест схемы: нет колонок с открытым токеном |
| CSRF | `SameSite=Lax` + `X-CSRF-Token` + проверка `Origin`/`Sec-Fetch-Site` | небезопасный метод без токена или с чужим Origin → `403 csrf_failed` |
| Bot-учётные данные в браузере | `/v2` отвергает `Authorization: Bearer` бота и `X-Telegram-User-ID` | тест на каждый `/v2` маршрут |
| Фиксация сессии | сессия создаётся только в exchange, новый случайный id; cookie с префиксом `__Host-` | тест: установленная клиентом cookie не принимается без строки в БД |
| Отозванный или истёкший доступ | `revoked_at`, idle/absolute сроки проверяются на каждом запросе, без кэша | тест logout и истечения по часам (fake clock) |
| Перебор токенов | 256 бит энтропии; лимит выдачи; одинаковый `401` | тест неразличимости ошибок |

## 7. План тестов (PostgreSQL, без внешних вызовов)

1. Миграция: `0015 → 0016 → 0015` на disposable БД; `alembic upgrade head`; модели соответствуют миграции.
2. Сервис: выдача ссылки, погашение, истечение, параллельный exchange, лимит выдачи, отзыв, idle/absolute сроки, продление не чаще раза в 5 минут.
3. HTTP: cookie-атрибуты, `no-store` на всех ответах включая ошибки, CSRF и Origin, отказ от bot-учётных данных в `/v2`, `feature_disabled` при выключенном флаге.
4. Совместимость: весь существующий набор Telegram/Copilot/delivery без изменений; бот без `WEB_AUTH_ENABLED` ведёт себя как раньше.
5. Изоляция: web-сессия пользователя A не читает `/v2/me` пользователя B; web-only пользователь (`telegram_id IS NULL`) существует, но ссылку из бота получить не может.

## 8. Порядок работ

| Шаг | Зависимость | Результат |
|---|---|---|
| B2.0 этот документ | — | согласование OQ-7 и объёма с владельцем |
| B2.1 миграция `0016` + модели + сервис | merge B1a в master | PR со схемой и сервисным слоем |
| B2.2 `/v2/auth/*`, `/v2/me`, зависимость web-сессии | B2.1 | PR с HTTP-слоем |
| B2.3 internal link + кнопка бота | B2.1 | PR в bot trust zone |
| B2.4 Caddy-маршрутизация `/api/v2` (D1) | B2.2 | ops-изменение, отдельное согласование |

До merge B1a никакая ветка не добавляет миграцию от `0015`; цепочка остаётся линейной: `0014 → 0015 (B1a) → 0016 (B2)`.

## 9. Открытые вопросы владельцу

- **OQ-7** — сроки сессии: idle 7 дней, absolute 30 дней.
- Домен и `WEB_APP_ORIGIN` для internal beta.
- Текст кнопки и сообщения со ссылкой в боте.
- Нужен ли список активных сессий и «выйти везде» в B2 или позже (C0 `SessionInfo`).
