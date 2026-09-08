# SMM AI Helper

Telegram-first marketing copilot built with FastAPI, aiogram and PostgreSQL. The MVP connects competitor analysis, a commercial creative package and an opt-in mentor explanation.

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
