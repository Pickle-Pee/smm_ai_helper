## Why

The repository can persist a multi-step `MarketingRun` and its `MarketingArtifact` outputs, but it has no durable record for one future asynchronous unit of work. Establishing that PostgreSQL contract before Redis or workers are introduced prevents transport state from becoming the source of truth and gives later workflow execution a transactional persistence boundary.

## What Changes

- Add a durable, run-optional `Job` aggregate in PostgreSQL for one future asynchronous execution request, with optional user attribution and optional MarketingRun/workflow-step association.
- Define an exact additive `jobs` table contract, a closed `pending -> running -> succeeded|failed` lifecycle, coherent payload/result/error/timestamp rules, and database constraints/indexes.
- Add a caller-transaction-owned internal persistence service for creation, lookup, run-scoped listing, and locked lifecycle transitions; methods may flush and never commit.
- Plan one additive Alembic migration from the current single head and deterministic upgrade/downgrade and revision-continuity verification.
- Preserve current MarketingRun/MarketingArtifact responsibilities, synchronous task behavior, Module Registry metadata, Marketing Orchestrator and Quality Gates behavior, and every public API/Telegram contract.
- Add directly related architecture/product documentation and a durable pre-implementation verification template.

## Capabilities

### New Capabilities

- `durable-job-persistence`: Durable Job storage, exact lifecycle coherence, transaction participation, and internal persistence operations without queue or execution behavior.

### Modified Capabilities

None.

## Impact

- **Persistence:** one future `jobs` table and one new Alembic revision; no existing table or historical row is rewritten.
- **Runtime implementation area:** future changes will be limited primarily to the SQLAlchemy Job model/status type, an internal Job persistence service, one migration, and focused tests. This proposal does not implement them.
- **Public contracts:** no request/response, FastAPI, Telegram, presenter, or public DTO change.
- **Existing domain contracts:** `MarketingRun` remains workflow progress, `MarketingArtifact` remains durable workflow output, and `TaskPipelineService` remains the current standalone-task pipeline.
- **External infrastructure and cost:** no Redis, queue framework, worker, scheduler, polling, delivery, OpenAI/LLM, QC, or new dependency/configuration is introduced.
- **Rollout:** after a later apply change, the additive migration must be deployed before any later producer creates Jobs. Until a separately reviewed queue/worker change exists, persisted Jobs are storage records only and nothing claims or executes them.

## Out of Scope

- Redis or any queue/worker framework, publication, claiming, polling, scheduling, delivery, module execution, Marketing Orchestrator execution, or Quality Gates execution integration.
- Retry/backoff, dead letters, leases, heartbeats, worker identity, idempotency/deduplication, per-user ordering, concurrency limits, cancellation, or timeout enforcement.
- API or Telegram endpoints/UX, LLM/OpenAI/QC calls, an outbox, or workflow-engine behavior.
- Changes to existing MarketingRun/MarketingArtifact schemas or behavior, Module Registry bindings/checksum, agents, presenters, `AgentRegistry`, `TaskPipelineService`, public result DTOs, or current model-call counts.
