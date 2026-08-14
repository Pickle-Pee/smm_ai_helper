# Backend instructions

These rules extend the repository-level `AGENTS.md` for work under `app/`.

- Keep routers thin. Do not add direct SQL, agent-specific rules, prompt construction, or orchestration to routers.
- Put persistence operations in services/repositories appropriate to the existing architecture.
- Keep external integrations behind service boundaries.
- Do not import Telegram/aiogram code into `app/`.
- Keep `AgentRunner` generic. Agent-specific input mapping belongs in `AgentInputBuilder` or a dedicated domain service.
- Keep `AgentRegistry` the source of truth for supported single-task agents.
- Do not turn `TaskPipelineService` into a multi-workflow engine. Multi-step MVP flows should use a separate workflow layer after the corresponding OpenSpec change is approved.
- Preserve the distinction between durable `BrandProfile` context and temporary conversation facts.
- For future queue work, PostgreSQL owns durable job state; Redis only transports/coordinates work.
- New public response fields or endpoint behavior require an OpenSpec delta and compatibility review.
- Prefer dependency injection for services that need deterministic unit tests.
- Log identifiers such as request/session/job/run IDs when the relevant domain object exists; do not log secrets or raw credentials.