# SMM AI Helper

Telegram-first marketing copilot built with FastAPI, aiogram and PostgreSQL. The MVP connects competitor analysis, a commercial creative package and an opt-in mentor explanation.

## Run locally with Docker Compose

Copy `.env.example` to `.env` only if `.env` does not already exist. Set `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN` and an independent random `BOT_BACKEND_TOKEN` shared by backend and bot. Keep the Compose service addresses in the example. Generate a service secret locally with `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 migrate backend worker bot
```

Compose starts PostgreSQL 15, Redis 7, a one-shot Alembic migration, the backend, worker and Telegram bot. The backend listens on `127.0.0.1:8000`. PostgreSQL and images use named volumes (`smm_db_data`, `smm_images`); backend and worker share `/data/images`. Normal container recreation preserves both. Stop with `docker compose down` (omit `--volumes` to retain results).

In a **private chat** with the bot:

```text
/brand Курс фотографии | Начинающие фотографы | Заявки на курс
/analyze https://example.com
```

Use a real publicly accessible competitor page instead of `example.com`. Alternatively supply the context for just this run: `/analyze URL | продукт | аудитория | цель`. Missing context is saved and requested through `/context ID | продукт | аудитория | цель`.

The analysis arrives in the background. Press **Создать креативный пакет** to generate the offer, headline, CTA, banner and a 15–60-second video script. Press **Объяснить решение** for the mentor explanation of that saved package. `/runs`, `/status ID`, `/result ID` retrieve progress and saved results after restart; `/redeliver ID` retries failed delivery without generation. A new `/analyze` message deliberately starts a new run; replaying the same update or continuation reuses existing work.

## Run without Docker

Use Python 3.11+ (the verified Windows environment uses `.venv/Scripts/python.exe`), PostgreSQL 15+ and Redis 7. Install `requirements.txt`, point `DATABASE_URL` and `REDIS_URL` at your local services, set `API_BASE_URL=http://127.0.0.1:8000` and `IMAGE_STORAGE_PATH` to one persistent absolute directory accessible by backend and worker. Set the same credentials as above in `.env`. Install DejaVu Sans on Linux for Cyrillic banner text; Windows uses Arial.

```bash
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# Separate terminals, same environment:
python -m app.worker
python -m bot.main
```

Redis accelerates wakeups. The worker also scans PostgreSQL, so it can recover and run while Redis is unavailable. Keep one polling bot per Telegram token. The API trusts only the service bearer token and its `X-Telegram-User-ID` actor header; IDs alone grant no access.

## Development

Use task -> implementation -> tests -> code review on a dedicated `codex/<task>` branch from `sale-ready`. `master` is release history. Existing OpenSpec contracts remain reference material; separate proposal/design/approval cycles are optional.

Read `AGENTS.md`, `ARCHITECTURE.md`, and `docs/product/mvp-functional-scope.md`. See `docs/development/openspec-codex.md` for the branch and verification workflow.

## Checks

```bash
python -m pytest
python -m compileall app bot
git diff --check
```

Schema changes require a new migration and verification on an explicitly disposable PostgreSQL database. `DURABLE_JOB_TEST_DATABASE_URL` must identify a database whose name contains `durable_job_test`; this suite performs destructive migration round trips. Never point it at shared data.

For full database coverage create **two separate disposable databases** and set:

```text
DURABLE_JOB_TEST_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@localhost:5432/durable_job_test_local
MVP_TEST_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@localhost:5432/smm_mvp_test_local
REDIS_TEST_URL=redis://localhost:6379/15
```

Then run `python -m pytest`. The DB and real Redis tests explicitly skip when their variables are absent. Run these suites serially: the disposable MVP fixture clears workflow queues, and migration tests change their schemas. CI provisions PostgreSQL and Redis and enables these suites.

The offline-provider smoke command is `python scripts/smoke_mvp.py` with `MVP_TEST_DATABASE_URL` set. It exercises the HTTP/worker/delivery path, real PostgreSQL, a crashed worker subprocess and replacement, and actual text/image HTTP adapters against closed test doubles. It never calls real OpenAI or Telegram. CI also builds the actual Docker image and verifies run/image persistence and ownership after backend/worker container recreation in an isolated Compose project with external providers disabled.

## Limits

Analysis uses the available text of one public HTML page, with bounded time, size and redirects. Private networks, authentication pages, browser-only rendering, compressed-only pages and non-HTML documents are unsupported; gated social pages may provide insufficient evidence. Quality Gates validate structured metadata and lineage; they do not verify the truth of model conclusions.

The MVP produces an image and a scene script, not an edited video. Provider calls may repeat after an ambiguous crash/timeout. Telegram may deliver a duplicate if it accepts a send immediately before the acknowledgement is lost. Completed artifacts remain recoverable independently of delivery. External costs and real model/Telegram quality require a separate live acceptance run.

See [workflow contracts and recovery](docs/development/marketing-mvp.md) and the [verification report](docs/development/mvp-verification-2026-09-09.md).
