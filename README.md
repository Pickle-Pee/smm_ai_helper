# SMM AI Helper

Telegram-first AI marketing copilot built with FastAPI, aiogram, PostgreSQL, and OpenAI APIs.

## Local run

```bash
docker-compose up --build
```

## Chat assistant

Example request:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "tg:123",
    "text": "Нужен контент-план для телеграм-канала про финансы для подростков",
    "attachments": []
  }'
```

Example with URL context:

```bash
curl -X POST http://localhost:8000/chat/message \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "tg:123",
    "text": "Посмотри сайт https://example.com и предложи, как улучшить первый экран",
    "attachments": []
  }'
```

## Development workflow

This repository uses OpenSpec + Codex + `AGENTS.md` + Git for spec-driven changes.

Start here:

- `AGENTS.md` — coding-agent rules and architecture invariants;
- `docs/development/openspec-codex.md` — branch/OpenSpec/Codex workflow;
- `openspec/config.yaml` — shared OpenSpec project context and artifact rules;
- `openspec/specs/` — current behavioral contracts;
- `ARCHITECTURE.md` — current and planned architecture;
- `docs/product/mvp-functional-scope.md` — product vision and MVP scope.

Install OpenSpec and configure Codex on a developer machine:

```bash
npm install -g @fission-ai/openspec@latest
openspec init --tools codex --profile core
openspec update
openspec validate --all --strict
```

OpenSpec-generated `.codex/skills/openspec-*` files should be regenerated through the CLI rather than edited manually.

## Baseline checks

```bash
pytest
python -m compileall app bot
```

For schema-changing work:

```bash
alembic upgrade head
```

For OpenSpec work:

```bash
openspec validate --all --strict
```