# Architecture

## Overview
The system is split into two parts:

- **Telegram bot (`bot/`)** – UI only. It renders questions, sends user answers to the backend, and displays text or images.
- **FastAPI backend (`app/`)** – all LLM logic, routing, clarification, worker execution, QC, and image generation.

## Backend flow (text)

1. **Router** (`app/services/orchestrator.py`) inspects the task and decides:
   - complexity (`light|hard`)
   - model (`gpt-4o-mini|gpt-5-mini`)
   - max output tokens
   - whether clarification/QC is required
2. **Clarifier** asks 1–3 questions per step (max 6 total).
3. **Worker** runs the selected SMM agent (`app/agents/`) using the unified OpenAI text client (`app/llm/openai_text.py`).
4. **QC** optionally validates the output and triggers one re-run if needed.

API endpoints:

- `POST /tasks/start`
- `POST /tasks/answer`
- `GET /tasks/{id}`
- `GET /tasks/by_user/{telegram_id}`

## Backend flow (images)

1. **ImageBriefAgent** (`app/agents/image_brief_agent.py`) produces a structured brief.
2. **Preset resolver** (`app/images/presets.py`) chooses a size.
3. **ImageOrchestrator** (`app/services/image_orchestrator.py`) generates:
   - `simple` → direct background generation
   - `template` → background + `TemplateRenderer` overlays text
   - `hybrid` → text prompt, fallback to template if low confidence

API endpoints:

- `POST /images/generate`
- `GET /images/{id}.png`

Images are cached by prompt/size and stored in `IMAGE_STORAGE_PATH`.

## Unified LLM layer

- Text: `app/llm/openai_text.py`
- Images: `app/llm/openai_images.py`

Both clients use shared timeouts/retry/backoff from `app/config.py`.
