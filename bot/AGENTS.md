# Telegram bot instructions

These rules extend the repository-level `AGENTS.md` for work under `bot/`.

- Telegram is an interface layer, not the business/domain layer.
- Handlers may map Telegram events to backend requests and render backend results, but must not call OpenAI directly.
- Do not duplicate backend validation or marketing decision logic in handlers.
- Do not keep durable user/workflow state only in process memory.
- Existing in-memory conveniences must not be expanded for new durable flows; future job/action state should use approved persistent/Redis-backed infrastructure.
- Keep callback payloads small and deterministic.
- Make failure messages understandable to the user without exposing stack traces or internal errors.
- Long-running workflow work belongs in queued workers; handlers acknowledge acceptance quickly.
- Preserve Telegram user identity mapping (`tg:<telegram_id>`) unless an approved change explicitly replaces the contract.
