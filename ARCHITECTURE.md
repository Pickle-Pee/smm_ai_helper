# Architecture

## Product boundary

`smm_ai_helper` is a Telegram-first AI marketing copilot. The runtime is intentionally split into interface, application/service, persistence, and external-model layers.

The current system supports standalone chat and marketing-agent tasks. The planned MVP adds a durable multi-step workflow:

`competitor analysis -> commercial creative package -> mentor explanation`

Planned components are explicitly marked below and are not current runtime behavior.

## Current runtime

```text
Telegram bot (aiogram)
        |
        v
FastAPI backend
  |-- ChatService
  |-- TaskPipelineService
  |-- BrandProfileService
  |-- UrlAnalyzer
  |-- ImageOrchestrator
        |
        +--> PostgreSQL
        +--> OpenAI text/image APIs
        +--> image storage
```

### Telegram interface

`bot/` is an interface layer. It maps Telegram updates to backend requests and renders replies, images, follow-up questions, and action buttons.

Marketing/business decisions should not be implemented in Telegram handlers.

### Chat flow

`POST /chat/message` delegates to `ChatService`.

The service coordinates:

1. conversation/message persistence;
2. scope guard;
3. recent chat memory;
4. URL/handle analysis through `ChatUrlService` / `UrlAnalyzer`;
5. facts and summary updates;
6. persistent `BrandProfile` lookup and merge with non-empty temporary conversation facts;
7. assistant response generation/policy/QC;
8. optional image intent through `ChatImageService`.

`BrandProfile` is durable user-owned brand context. `Conversation.facts_json` is temporary conversational context and must not automatically overwrite the durable profile.

### Single-task flow

`POST /tasks/start` and `POST /tasks/answer` delegate to `TaskPipelineService`.

High-level flow:

```text
Task router endpoint
 -> user / agent validation
 -> TaskPipelineService
 -> TaskRouter
 -> ClarificationService (if needed)
 -> AgentRunner
 -> QCService (if needed)
 -> TaskImageService (optional)
 -> final task persistence/history
```

Supported standalone agent types currently include strategy, content, analytics, promo, and trends.

Task sessions are temporary durable records while clarification is in progress. Completed results are saved to task history.

See `docs/task_pipeline.md` for the detailed task architecture.

### URL analysis

`UrlAnalyzer` extracts/normalizes a bounded set of URLs/social targets, fetches lightweight page signals, and stores reusable summaries in `UrlCache` when database access is available.

Upcoming competitor-analysis work should reuse this capability rather than introduce an unrelated scraper without an approved design change.

### Image generation

`ImageOrchestrator` coordinates `ImageBriefAgent`, preset resolution, OpenAI image generation, optional template rendering, local storage, and image retrieval.

Public endpoints:

- `POST /images/generate`
- `GET /images/{image_id}.png`

Upcoming commercial-creative work should reuse this pipeline.

## Persistence ownership

PostgreSQL is the current durable source of truth for:

- users;
- tasks and task sessions;
- conversations and messages;
- brand profiles;
- URL cache.

Future durable workflow/job state also belongs in PostgreSQL.

## Planned MVP workflow architecture

The following is planned and requires OpenSpec changes before implementation:

```text
Telegram / API ingress
        |
        v
MarketingWorkflowService
        |
        +--> MarketingRun / MarketingArtifact (PostgreSQL)
        |
        +--> JobService (PostgreSQL durable status)
                |
                v
             Redis queue
                |
                v
             Workers
        +-------+--------+
        |       |        |
 competitor  creative  mentor
 analysis    package   insight
        |       |        |
        +--> UrlAnalyzer |
        +--> BrandProfile|
                +--> ImageOrchestrator
                +--> OpenAI APIs
```

### Planned queue invariant

Redis will be transport/coordination infrastructure, not the canonical record of job completion. A worker must be able to recover work from durable PostgreSQL job state after restart or Redis loss according to the approved job/queue specifications.

### Planned workflow invariant

`TaskPipelineService` remains the single standalone marketing-task pipeline. Multi-step product workflows should be orchestrated by a dedicated workflow layer whose artifacts can feed later steps.

## Specification and agent workflow

- Current observable behavior is documented under `openspec/specs/`.
- Proposed behavior changes live under `openspec/changes/` until implemented and archived.
- `AGENTS.md` files contain persistent Codex implementation constraints.
- Product vision lives under `docs/product/` and does not automatically override current behavioral specs.