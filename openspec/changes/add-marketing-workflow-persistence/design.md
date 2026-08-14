# Design: Durable marketing workflow persistence

## Context

The repository already has durable PostgreSQL models for `User`, completed `Task` history, `TaskSessionRecord`, `Conversation`, `Message`, `BrandProfile`, and `UrlCache`. `TaskPipelineService` is intentionally a single standalone-task pipeline. Completed task persistence is handled separately by `TaskResultService`.

The MVP needs a durable record spanning multiple product steps. That record must not be represented only by a task session because task sessions are temporary clarification state and are deleted when a standalone task completes.

This change introduces the storage substrate only. A later `MarketingWorkflowService` will orchestrate steps, and later job/Redis changes will provide asynchronous execution.

## Goals

- Add a durable parent record for one marketing workflow execution.
- Add durable structured artifacts that later workflow steps can consume.
- Make artifact writes retry-friendly through a stable per-run artifact key.
- Keep transaction ownership suitable for later worker/orchestrator operations.
- Keep existing runtime/public contracts unchanged.
- Keep `TaskPipelineService` focused on standalone tasks.

## Non-Goals

- Implement workflow orchestration.
- Implement competitor analysis, creative generation composition, or mentor explanation.
- Add background jobs, Redis, retries, leases, or cancellation mechanics.
- Add HTTP/Telegram interfaces for marketing runs.
- Refactor unrelated task/chat code.

## Decision 1: Add `marketing_runs`

Proposed model: `MarketingRun`.

Fields:

| Field | Type | Notes |
|---|---|---|
| `run_id` | `String(64)` | Primary key; generated UUID hex; stable external/internal identifier |
| `user_id` | nullable FK -> `users.id` | Indexed; anonymous runs are allowed |
| `workflow_type` | `String(64)` | Indexed; identifies workflow family |
| `status` | `String(32)` | Indexed; initial value `created` |
| `current_step` | nullable `String(64)` | Current logical workflow step |
| `input_json` | nullable `JSONB` | Immutable-ish initial workflow input/context |
| `state_json` | nullable `JSONB` | Mutable workflow state/checkpoint data |
| `error` | nullable `Text` | Last terminal/diagnostic error description |
| `created_at` | `DateTime` | Creation timestamp |
| `updated_at` | `DateTime` | Updated whenever persisted run state changes |

Initial lifecycle vocabulary:

- `created`
- `running`
- `completed`
- `failed`
- `cancelled`

This change stores statuses as strings, consistent with existing models. A later job/workflow change may add stricter transition validation without requiring a schema rewrite.

## Decision 2: Add `marketing_artifacts`

Proposed model: `MarketingArtifact`.

Fields:

| Field | Type | Notes |
|---|---|---|
| `id` | `Integer` | Primary key |
| `run_id` | FK -> `marketing_runs.run_id` | Indexed; cascade delete with its run |
| `artifact_key` | `String(128)` | Stable logical slot within one run |
| `artifact_type` | `String(64)` | Indexed; e.g. `competitor_analysis`, `creative_package`, `mentor_insight` |
| `step` | nullable `String(64)` | Producing logical step |
| `payload_json` | `JSONB` | Structured durable artifact payload |
| `created_at` | `DateTime` | Creation timestamp |
| `updated_at` | `DateTime` | Updated on retry/upsert |

Database constraint:

```text
UNIQUE (run_id, artifact_key)
```

This makes a worker retry idempotent at the logical artifact-slot level: persisting `competitor_analysis` for the same run updates the slot instead of creating duplicates.

Artifacts are deliberately self-contained rather than foreign-keyed to `Task`. A future orchestrator may reuse agent/task services internally, but the multi-step product contract should not require a historical standalone task row to exist.

## Decision 3: Persistence service boundary

Add `MarketingWorkflowPersistenceService` under `app/services/`.

Expected operations:

- `create_run(...)`
- `get_run(run_id)`
- `update_run(...)`
- `upsert_artifact(...)`
- `get_artifact(run_id, artifact_key)`
- `list_artifacts(run_id)`

The service SHALL NOT call OpenAI, Telegram, URL fetching, or image generation.

### Transaction ownership

Persistence methods should add/update/flush database objects but should not force commits internally. The caller owns the transaction boundary. This is intentional so later workflow/worker code can atomically persist combinations such as:

```text
artifact write + current_step advance + run status update
```

without partial commits between operations.

This differs from some older services that commit internally; new workflow persistence should establish the safer transaction boundary for asynchronous orchestration.

## Decision 4: Relationships and deletion

- `User.marketing_runs` -> many marketing runs.
- `MarketingRun.user` -> optional owner.
- `MarketingRun.artifacts` -> artifacts for the run.
- Deleting a `MarketingRun` should cascade-delete its artifacts at the database relationship/foreign-key level.
- No existing user/task/profile relationship behavior changes.

## Decision 5: Deterministic artifact listing

`list_artifacts(run_id)` should use an explicit deterministic order, proposed as ascending artifact `id`. The product must not depend on unspecified database row order.

## Migration

Create a new Alembic revision from current head `20260711_0002`.

Upgrade:

1. create `marketing_runs`;
2. create required indexes;
3. create `marketing_artifacts`;
4. create unique constraint `(run_id, artifact_key)` and indexes.

Downgrade:

1. drop artifact indexes/table;
2. drop run indexes/table.

Do not modify either existing migration.

## Expected files

Runtime/schema work should be limited primarily to:

- `app/models.py`
- `app/services/marketing_workflow_persistence_service.py`
- `migrations/versions/<new_revision>_add_marketing_workflow_persistence.py`
- tests for the new persistence service/models

No router or Telegram-handler change is expected in this OpenSpec change.

## Risks and mitigations

### JSON payload growth

Artifacts may become large. For MVP structured text/metadata this is acceptable in JSONB. Binary images must continue to be stored by image storage with references/metadata in artifacts, not embedded as image bytes in JSONB.

### Status semantics evolve later

The initial string statuses are intentionally minimal. Strict state-transition rules belong to orchestration/job changes, not this schema bootstrap.

### Concurrent artifact retries

The database unique constraint prevents duplicate logical artifact slots. The service upsert implementation must handle the unique key deterministically and tests must cover updating an existing slot.

## Rollback

Because no existing runtime path depends on these tables in this change, rollback is the Alembic downgrade that removes the two new tables. Existing tasks, users, conversations, profiles, and URL cache data are unaffected.
