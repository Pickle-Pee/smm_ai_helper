# Architecture

## Product boundary

`smm_ai_helper` is a Telegram-first AI marketing copilot. The runtime is intentionally split into interface, application/service, persistence, and external-model layers.

The system supports standalone chat/tasks and a durable multi-step MVP workflow:

`competitor analysis -> commercial creative package -> mentor explanation`

See `docs/development/marketing-mvp.md` for execution, recovery and HTTP contracts.

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
  |-- MarketingWorkflowService -> PostgreSQL jobs + Redis wakeups -> worker
  |-- DeliveryService -> bot sender -> Telegram
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
 -> durable standalone claim (or replay of completed_response)
 -> TaskRouter
 -> ClarificationService (if needed)
 -> AgentRunner
 -> QCService (if needed)
 -> TaskImageService (optional)
 -> final task persistence/history
```

Supported standalone agent types currently include strategy, content, analytics, promo, and trends.

Task sessions retain answers and the canonical `completed_response` after completion. PostgreSQL claims serialize continuation before routing/model/QC/image calls; waiting requests release their transactions between checks. `TaskCompletionService` fences the owner and atomically saves one Task history row, the response and claim release. Later answers replay the response without external work. Failed owners release their claim; crashed owners can be replaced after lease expiry. See the task contract for bounded timeout/recovery and external-provider limitations.

See `docs/task_pipeline.md` for the detailed task architecture.

### Internal Marketing Orchestrator planning foundation

The semantic foundation in `app/marketing_copilot/` prepares intent, resolved context and deterministic depth proposals above the existing Chat / Tasks / fixed Workflow boundaries. Its explicitly composed internal `MarketingCopilotService` now coordinates these proposals with deterministic tools, synchronous modules and durable graph start. It is not connected to API, Telegram or production workers. An explicitly injected model callback may interpret text into strict `MarketingIntent`; it cannot supply an executor, Job type or execution binding. A pure policy selects CONVERSATION, DIRECT_TOOL, SINGLE_MODULE or WORKFLOW using allowlisted mappings and Registry metadata. These selections are proposals, never execution authorization.

Its context resolver returns the existing `PlanningContext`, preserving source provenance and the precedence current explicit request > project/run > BrandProfile > conversation fallback. Saved artifacts remain upstream references/findings. The adapter maps only module/workflow proposals to the unchanged `RequestInterpretation` selector contract. `strategy_builder_v1` is a future scenario proposal and remains unsupported by the existing planner. See [unified request foundation](docs/development/unified-request-contracts.md) for contracts, input/authorization boundaries and limitations.

`app/marketing_orchestrator/` is a deterministic, side-effect-free internal planning boundary:

```text
typed RequestInterpretation + caller-authorized tagged PlanningContext
 -> minimal Registry-backed graph
 -> deterministic validation
 -> validated, blocked, or unsupported planning result
```

It supports `explicit_single_module_v1`, `new_positioning_v1`, and `competitive_positioning_v1`. `new_positioning_v1` plans parallel `MARKET_ANALYSIS` and `COMPETITOR_ANALYSIS` nodes followed by dependent `POSITIONING`. Context is scoped by explicit module/scenario relevance; the planner does not query BrandProfile, conversation, URL, artifact, or workflow persistence services.

This boundary is not connected to API or Telegram ingress and does not replace `TaskRouter`, `AgentRunner`, or `TaskPipelineService`. It loads no Orchestrator prompt and calls no model, agent, QC, database, Redis, queue, or worker. Module Registry `1.0.0` has zero execution bindings, so every valid result remains `PLANNING_ONLY`; planning does not start workflow execution.

### Internal deterministic Quality Gates foundation

The implemented deterministic Quality Gates boundary evaluates typed results. Its Registry-derived readiness remains `PLANNING_ONLY`, while the fixed MVP consumes its structural gate outcomes through an explicit adapter:

```text
caller-supplied immutable normalized module result
 -> exact contract and Registry metadata validation
 -> RFC-8785 batch fingerprint / selected-evidence contradiction / typed aggregate decisions
 -> synthesis-eligibility manifest (data only)
```

The foundation remains pure and non-persistent: it does not call a module, agent, LLM or `QCService`, query context or persistence, create Jobs, use Redis/workers, or synthesize prose. The fixed MVP now calls it through the explicit `app/workflows/quality.py` adapter before saving an artifact. Existing standalone agent results remain unchanged. Registry `1.0.0` validates identities, declared output membership and registered handoffs; workflow-specific schemas are defined separately. The gate verifies structured metadata and provenance relationships, not semantic truth.

Runtime ownership is `app/marketing_orchestrator/quality_gates/` with contracts/errors/evaluation/propagation/contradiction/decision modules and minimal internal exports. It depends only on public read-only Module Registry boundaries. Existing planner and validator remain independent and do not import Quality Gates; no public API or circular dependency is introduced.

### Internal module execution foundation

`app/module_execution/` defines the runtime-neutral `module_executor.v1` boundary:

```text
ModuleId -> declarative ExecutionBinding (executor_key, contract_version, exact, evidence)
         -> explicitly injected ModuleExecutorRegistry
         -> ModuleExecutorDispatcher -> ModuleExecutor.execute(request) -> ModuleExecutionResult
```

The request reuses the Orchestrator's immutable `ContextPacket`. Complete predecessor results carry a producer node ID, module-specific frozen JSON payload and the existing Quality Gates `NormalizedModuleResult`; there is no parallel claims/evidence model. The dispatcher validates exact key/version/module compatibility, invokes once, checks the result envelope, and propagates executor errors unchanged. It does not evaluate Quality Gates, retry, persist, schedule or own resources.

Python dependencies point from this execution package to declarative `module_registry` types, Orchestrator context contracts and Quality Gates result contracts. Module Registry no longer imports legacy `AgentRegistry` or checks runtime implementation availability. Neither planning nor Quality Gates imports the new execution package.

Registry `1.0.0` remains the current default, byte-for-byte unchanged, metadata-only and rejecting every binding. Registry resources 1.0.0 and 1.1.0 remain unchanged. Explicit `ModuleRegistry.load("1.1.0")` provides exactly three approved exact bindings: `COMPETITOR_ANALYSIS -> competitor_analysis.v1`, `POSITIONING -> positioning.v1`, and `CREATOR -> creator.v1`, all using `module_executor.v1`. The other twelve descriptors remain metadata-only in 1.1.0. Explicit 1.2.0 adds `MARKET_ANALYSIS -> market_analysis.v1`, `VIRTUAL_CMO -> virtual_cmo.v1`, and `EXPERIMENTS -> experiments.v1`, also exact `module_executor.v1`; nine modules remain metadata-only. Descriptor metadata is identical across all three versions. Unknown versions and non-approved binding sets fail closed.

The separate `app/module_execution/executors/` package supplies three implementations in its unchanged default 1.1 composition, or six when the factory receives `registry_version="1.2.0"`, with injected single-attempt model and source-analysis capabilities. They use ExpertInstructionComposer, strict bounded structured outputs, scoped inputs, first-party/public-page provenance and confidence-capped predecessor lineage. Missing inputs/tools or unsupported assets return typed BLOCKED results. They construct Quality Gates contracts but never run its evaluator; evaluation remains the outer caller's concern. There are no mutable global production registrations.

The executable registry and implementations are internally callable only. The internal Copilot application service and durable graph runtime consume them explicitly; no API, Telegram, production worker main or MarketingWorkflowService consumes them. `AgentRegistry`/`AgentRunner` and fixed `MarketingExecutors` remain in place. The optional cache-free UrlAnalyzer composition opts into propagating fetch errors; legacy callers retain their existing failure behavior. The generic Orchestrator stays `PLANNING_ONLY`. See [first module executors](docs/development/first-module-executors.md) and [module execution foundation](docs/development/module-execution-foundation.md).

### Internal strategy intelligence executors

Registry 1.2.0 extends the same dispatcher/result/Quality Gates boundary. MARKET_ANALYSIS
uses authorized first-party customer/market facts, explicitly supplied source excerpts,
accepted predecessor results or explicitly supplied public URLs through an injected
safe UrlAnalyzer capability. It has no search provider and treats absent sizing data
as unknown. Supplied primary/secondary provenance is preserved; observed pages are
primary evidence of their text, not independent verification of their assertions.

VIRTUAL_CMO synthesizes a bounded strategy from an explicit business goal, known
business/product context and accepted findings. It is an expert, not the Orchestrator
or MarketingCopilotService. EXPERIMENTS turns accepted strategic/positioning hypotheses
into structured falsifiable designs with parent lineage. Structured strategy items and
experiment fields are included in normalized claims and remain behind full-claim acceptance.
BUSINESS_DIAGNOSTICS remains economics-first and metadata-only; it is not repurposed
as an own-site/product analyzer. No Strategy Builder graph, production ingress,
worker wiring, delivery changes or migration is introduced. See
[strategy intelligence executors](docs/development/strategy-intelligence-executors.md).

### Internal unified Copilot application

`MarketingCopilotService.execute(CopilotRequest)` interprets once, resolves caller-authorized
context through `ContextResolver`, applies `ExecutionPolicy`, then dispatches:

```text
DIRECT_TOOL   -> deterministic tool registry -> Decimal funnel calculator
SINGLE_MODULE -> scoped planner packet -> shared dispatcher -> Quality Gates
WORKFLOW      -> planner -> PlanCompiler -> GraphExecutionService.start_compiled_run
CONVERSATION  -> typed conversation_delegate for future chat ingress
```

The fast paths create no MarketingRun, Job or JobExecution. Only Registry 1.1.0 bound
modules execute; no legacy fallback or application-level provider retry exists.
Workflow start returns a durable identity acknowledgement; `ModuleGraphWorker` owns
later execution. Actor + request key deterministically identify a run; the existing
runtime compares the compiled plan and rejects a different plan under the same key.
`PlanCompiler` and the runtime-owned `EXECUTABLE_SCENARIOS` remain the workflow
authorization boundary.

Success and upstream reuse require result acceptance **and every current claim** in
the gate manifest. Partial claim exclusion cannot release an unfiltered payload.
This invariant applies to synchronous presentation, graph completion and persisted
artifact reload. Blocking/unsupported outcomes return one typed grouped clarification.

For `competitive_positioning_v1`, an explicit competitor URL plus authorized SITE_FETCH
makes pre-collected observable evidence optional. The URL remains an unverified fetch
target; executor fetch failure may block execution. `new_positioning_v1` is unchanged.
No schema migration or production ingress was added. See
[unified Copilot execution](docs/development/unified-copilot-execution.md).

### Internal durable module graph execution

`app/orchestration_runtime/` compiles validated planning-only plans using explicit
Registry 1.1.0 or 1.2.0 and an injected executor registry. The immutable approved execution-version set contains exactly these two versions. Compilation persists the exact version; reload loads that version, never upgrades a 1.1 plan. Metadata compatibility still requires exact equality to planning Registry 1.0 after removing availability/bindings. The first executable vertical is
`competitive_positioning_v1`: COMPETITOR_ANALYSIS -> POSITIONING. The existing
`new_positioning_v1` is outside the runtime-owned immutable `EXECUTABLE_SCENARIOS`
allowlist, which contains exactly `explicit_single_module_v1` and
`competitive_positioning_v1`. Planning support does not grant execution permission;
MARKET_ANALYSIS is bound only in explicit Registry 1.2.0; binding availability does not authorize new scenarios.

Immutable `compiled_execution_plan.v1` revisions live in `orchestration_plans`,
owned by MarketingRun (`orchestration_graph.v1`). Ready nodes become distinct
`orchestration.module` Jobs. JobExecution owns bounded attempts and fenced leases;
accepted full typed results become revision-scoped `module_artifact.v1` artifacts.
A run lock serializes advance. Artifact persistence, Job success and dependent
scheduling commit atomically; Redis is only a best-effort wakeup.

The internal ModuleGraphWorker restores the plan and upstream results from SQL,
dispatches outside transactions, and evaluates Quality Gates before acceptance.
BLOCKED results block the run; quality rejection fails it without downstream work.
Corrupt persisted contracts fail closed. Restart needs no process-local progress.
No Telegram/API ingress or production worker lane consumes this runtime. See
[durable module graphs](docs/development/durable-module-graph-runtime.md) for
contracts, authorization, serialization bounds, lock order and recovery tests.

### URL analysis

`UrlAnalyzer` extracts/normalizes a bounded set of URLs/social targets, fetches lightweight page signals, and stores reusable summaries in `UrlCache` when database access is available.

The competitor executor reuses this capability. Fetches validate public DNS/IP addresses at connection time, recheck redirects, and bound time and bytes. Cache I/O uses independent short transactions.

### Image generation

`ImageOrchestrator` coordinates `ImageBriefAgent`, preset resolution, OpenAI image generation, optional template rendering, local storage, and image retrieval.

Public endpoints:

- `POST /images/generate`
- `GET /images/{image_id}.png`

The creative executor reuses this pipeline and renders the saved headline/CTA locally onto the generated background. A shared persistent volume makes owner-scoped images available after worker/backend recreation.

## Persistence ownership

PostgreSQL is the current durable source of truth for:

- users;
- tasks and task sessions;
- conversations and messages;
- brand profiles;
- URL cache.
- marketing workflow runs;
- named marketing workflow artifacts.

Durable Job state, execution attempts and delivery state also belong in PostgreSQL.

### Implemented durable Job persistence

OpenSpec change `add-durable-job-persistence` defines the `jobs` table and internal persistence service now used by `MarketingWorkflowService`. A Job is one durable execution request; it does not replace `MarketingRun` workflow progress or `MarketingArtifact` output.

- Ownership is exclusive: MarketingRun-owned, direct-user-owned, or trusted-internal system. There is no public anonymous Job class. A workflow step is valid only for a run-owned Job.
- Run-owned and direct-user-owned Jobs are operational aggregate children deleted with their owner through database/ORM cascade; they are not retained audit history and owner deletion never reclassifies work as system-owned.
- Request identity/input and ownership are immutable through the supported persistence service. Before transition SQL, tracked target immutable/version/owner-relationship, owner-collection, or deletion history is rejected without clearing caller state; ordinary untracked in-place JSON is replaced by the locked persisted row. The service deep-copies bounded input JSON and accepts only caller-sanitized failure strings. Direct session writes remain unsupported rather than universally blocked.
- The closed lifecycle is `pending/version=0 -> running/version=1 -> succeeded|failed/version=2`. Every transition requires the caller's exact observed version under the row lock, so only one request based on a given version can succeed. Retry, cancellation, timeout, delivery, and dead-letter states are not part of this foundation.
- One injected aware UTC clock owns creation/transition instants. Job mutations add/flush without refresh and may participate atomically with MarketingRun/MarketingArtifact changes, but the caller owns commit/rollback.
- PostgreSQL commit establishes durability. The foundation alone does not execute work; the additive workflow layer owns publication, leases, attempts, execution and delivery.

See `docs/product/durable-job-persistence.md`. The persistence service and migration `20260825_0004` are implemented; execution belongs to the workflow layer.

## Implemented MVP workflow architecture

The workflow extends the implemented persistence foundations:

```text
Telegram / API ingress
        |
        v
MarketingWorkflowService
        |
        +--> MarketingRun / MarketingArtifact (PostgreSQL)
        |
        +--> JobPersistenceService (implemented PostgreSQL persistence)
                |
                v
             Redis wakeups + PostgreSQL due scan
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

### Queue invariant

Redis transports wakeups; PostgreSQL stores canonical state. Workers reclaim expired leases with fencing tokens and bounded retries after restart or Redis loss. Artifact, job completion, run transition and Telegram delivery parts commit atomically. The bot claims and acknowledges deliveries independently of generation.

### Workflow invariant

`TaskPipelineService` remains the standalone pipeline. The dedicated workflow layer snapshots BrandProfile/current business inputs, executes analysis and creative on request, and enables the mentor only after an explicit continuation. Later steps consume saved artifacts. See README for commands and recovery behavior.

## Specification and agent workflow

- Current observable behavior and verification are documented in README, this architecture and `docs/development/marketing-mvp.md` / `docs/task_pipeline.md`, alongside code and tests.
- `openspec/specs/` and `openspec/changes/` preserve useful baseline contracts and design history. Unarchived changes may already be implemented; archival is optional.
- `AGENTS.md` files contain persistent Codex implementation constraints.
- Product documents distinguish implemented fixed scope from broader vision. Use task -> implementation -> tests -> code review; no separate OpenSpec approval cycle is required.

Production generic Orchestrator ingress, arbitrary execution of all 15 Registry modules, autonomous replanning and generic synthesis remain future work. Campaign execution, CRM integrations, final video generation/editing and production deployment are outside the implemented MVP. Neither provider calls nor Telegram delivery promise exactly-once external effects.
