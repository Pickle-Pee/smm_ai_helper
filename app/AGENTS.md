# Backend instructions

These rules extend the repository-level `AGENTS.md` for work under `app/`.

- Keep routers thin. Do not add direct SQL, agent-specific rules, prompt construction, or orchestration to routers.
- Put persistence operations in services/repositories appropriate to the existing architecture.
- Keep external integrations behind service boundaries.
- Do not import Telegram/aiogram code into `app/`.
- Keep `AgentRunner` generic. Agent-specific input mapping belongs in `AgentInputBuilder` or a dedicated domain service.
- Keep `AgentRegistry` the source of truth for supported single-task agents.
- Do not turn `TaskPipelineService` into a multi-workflow engine. Multi-step MVP flows use a separate workflow layer.
- Preserve the distinction between durable `BrandProfile` context and temporary conversation facts.
- PostgreSQL owns current Job, JobExecution and delivery state; Redis carries non-authoritative wakeups and workers recover through PostgreSQL due scans.
- Standalone task claims are independent of workflow workers/Redis. Commit the claim before external work and fence completion; never hold a transaction around model, QC or image calls.
- Review compatibility and document new public fields or endpoint behavior alongside implementation.
- Prefer dependency injection for services that need deterministic unit tests.
- Log identifiers such as request/session/job/run IDs when the relevant domain object exists; do not log secrets or raw credentials.
