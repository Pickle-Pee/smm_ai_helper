# Architecture

## Overview
The system is split into two parts:

- **Telegram bot (`bot/`)** – UI only. It sends every user message to the backend and renders replies, follow-up questions, and action buttons.
- **FastAPI backend (`app/`)** – all LLM logic: context memory, URL analysis, intent routing, response policy, and quality control.

## Backend flow (chat)

1. **Chat endpoint** (`POST /chat/message`) receives user text and stores it in `messages`.
2. **URL analyzer** (`app/services/url_analyzer.py`) extracts and summarizes the first URL (if present) with caching.
3. **Facts extractor** (`app/services/facts_extractor.py`) updates structured facts (`conversations.facts_json`).
4. **Summary updater** (`app/services/summary_updater.py`) refreshes `conversations.summary`.
5. **Assistant core** (`app/services/assistant_core.py`) generates a strict JSON reply.
6. **QC shortener** (`app/services/qc_shortener.py`) + **response policy** (`app/services/response_policy.py`) enforce brevity and single-question rules.
7. Assistant reply is stored in `messages` and returned.

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
