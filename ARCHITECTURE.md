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

### Internal Marketing Orchestrator planning foundation

`app/marketing_orchestrator/` is a deterministic, side-effect-free internal planning boundary:

```text
typed RequestInterpretation + caller-authorized tagged PlanningContext
 -> minimal Registry-backed graph
 -> deterministic validation
 -> validated, blocked, or unsupported planning result
```

It supports only `explicit_single_module_v1` and `new_positioning_v1`. The latter plans parallel `MARKET_ANALYSIS` and `COMPETITOR_ANALYSIS` nodes followed by dependent `POSITIONING`. Context is scoped by explicit module/scenario relevance; the planner does not query BrandProfile, conversation, URL, artifact, or workflow persistence services.

This boundary is not connected to API or Telegram ingress and does not replace `TaskRouter`, `AgentRunner`, or `TaskPipelineService`. It loads no Orchestrator prompt and calls no model, agent, QC, database, Redis, queue, or worker. Module Registry `1.0.0` has zero execution bindings, so every valid result remains `PLANNING_ONLY`; planning does not start workflow execution.

### Internal deterministic Quality Gates foundation

OpenSpec change `add-orchestrator-quality-gates` implements an internal planning-only boundary:

```text
caller-supplied immutable normalized module result
 -> exact contract and Registry metadata validation
 -> RFC-8785 batch fingerprint / selected-evidence contradiction / typed aggregate decisions
 -> synthesis-eligibility manifest (data only)
```

It is current internal code but is not connected to a workflow execution or user-facing path. The foundation remains pure and non-persistent: it does not call a module, agent, LLM or the existing model-based `QCService`; query context or persistence; create Jobs; use Redis/workers; generate a revised plan; or synthesize user-facing prose. Existing heterogeneous agent results and presenters require later explicit adapters and remain unchanged. Registry `1.0.0` can validate identities, declared output membership and registered handoffs but does not define invocation-specific required result schemas.

Runtime ownership is `app/marketing_orchestrator/quality_gates/` with contracts/errors/evaluation/propagation/contradiction/decision modules and minimal internal exports. It depends only on public read-only Module Registry boundaries. Existing planner and validator remain independent and do not import Quality Gates; no public API or circular dependency is introduced.

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
- marketing workflow runs;
- named marketing workflow artifacts.

Future durable Job state also belongs in PostgreSQL.

### Approved durable Job persistence contract (not implemented)

OpenSpec change `add-durable-job-persistence` defines an additive `jobs` table and an unused internal persistence service. A Job is one durable future execution request; it does not replace `MarketingRun` workflow progress or `MarketingArtifact` output.

- Ownership is exclusive and optional: MarketingRun-owned, runless user-owned, or system/anonymous. A workflow step is valid only for a run-owned Job.
- The closed lifecycle is `pending -> running -> succeeded|failed`; retry, cancellation, timeout, delivery, and dead-letter states are not part of this foundation.
- Job mutations may add/flush and participate atomically with MarketingRun/MarketingArtifact changes, but the caller owns commit/rollback.
- PostgreSQL commit establishes durability. A persisted Job is inert: this contract introduces no publication, claim, polling, execution, Redis, worker, LLM/QC, API, or Telegram behavior.

See `docs/product/durable-job-persistence.md`. Runtime behavior requires a later apply task after the OpenSpec artifacts are accepted.

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
        +--> JobPersistenceService (approved PostgreSQL contract; not implemented)
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
