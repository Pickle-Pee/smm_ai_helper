# Migration Plan: Contextual Chat Assistant

## Current flow (audit)
- **Bot → backend → agents**: the Telegram bot currently guides users through static agent-specific questions, then calls backend agent endpoints to produce results. The backend uses agent classes for strategy/content/analytics/promo/trends and stores results in tasks.
- **Static questions**: `bot/handlers/agent_flow.py` defines `AGENT_CONFIG` with hardcoded question lists and a step-by-step FSM. The bot collects answers and calls `/agents/{agent_type}/run`.
- **Response formatting**: formatting helpers live in `bot/handlers/agent_flow.py` (e.g., `format_strategy_result`, `format_content_result_digest`) and are used to render agent outputs.

## Migration approach
1. **Introduce a new chat endpoint**: `/chat/message` becomes the primary entry point, using conversation memory, URL analysis, and a single-question policy.
2. **Retain legacy agents as fallback**: keep `/agents/*` and the current menu flow operational while the chat assistant matures.
3. **Shift bot to free chat**: all plain text messages go to `/chat/message`, with follow-up questions and action buttons handled by the bot.
4. **De-emphasize static questions**: UI no longer asks fixed sequences; the assistant asks at most one question per turn.

## What we remove vs reuse
### Remove (primary path)
- Static question flow in `bot/handlers/agent_flow.py` from the main UX.
- Direct user-facing “agent selection” as the default entry point.

### Reuse (fallback)
- Agent endpoints (`/agents/*`) and existing agent classes.
- Task history endpoints (`/tasks/*`).

### New components
- `app/routers/chat_router.py` – unified chat entry point.
- `app/services/assistant_core.py`, `facts_extractor.py`, `summary_updater.py`, `qc_shortener.py`.
- `app/services/url_analyzer.py` – URL extraction and summarization with caching.
- `app/services/intent_router.py`, `response_policy.py`.
- Conversation memory tables: `conversations`, `messages`, `url_cache`.
