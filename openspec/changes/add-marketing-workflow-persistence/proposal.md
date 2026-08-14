# Change: Add durable marketing workflow persistence

## Why

The current system persists standalone tasks, task clarification sessions, conversations, brand profiles, and URL cache data, but it has no durable parent record for a multi-step marketing workflow and no first-class storage for artifacts produced by individual workflow steps.

The MVP flow — competitor analysis -> commercial creative package -> mentor explanation — needs durable state that can survive process restarts and can later be coordinated by queued workers. Adding this persistence layer first keeps future orchestration and queue changes small and prevents `TaskPipelineService` from becoming a multi-workflow state machine.

## What Changes

- Add a durable `MarketingRun` record for one multi-step marketing workflow execution.
- Add durable `MarketingArtifact` records attached to a run.
- Support named artifact keys so retries can update the same logical artifact instead of creating uncontrolled duplicates.
- Track run lifecycle status, current step, input/state JSON, timestamps, and error information.
- Associate a run with a persisted user when known while still allowing anonymous runs.
- Add a persistence service for creating/loading/updating runs and upserting/listing artifacts.
- Add an Alembic migration and automated tests.
- Keep existing `/chat`, `/tasks`, `/images`, `/brand-profile`, and Telegram behavior unchanged.

## Capabilities

### New Capabilities

- `marketing-workflow-persistence`: durable storage and retrieval of multi-step marketing runs and their artifacts.

### Modified Capabilities

- None.

## Out of Scope

- Redis or any queue implementation.
- Durable background jobs, retry scheduling, leases, or worker heartbeats.
- Competitor-analysis implementation.
- Creative-package implementation.
- Mentor-insight implementation.
- Multi-step workflow orchestration.
- New public HTTP or Telegram commands/endpoints.
- Automatic migration of historical standalone `Task` rows into marketing runs.

## Impact

### Database

Adds new PostgreSQL tables and indexes. Existing tables remain backward compatible and existing migrations are not edited.

### Runtime

No existing public runtime behavior changes. The new persistence service is infrastructure for later OpenSpec changes.

### Rollout

Apply the new Alembic revision before deploying code that begins creating marketing runs. Because no existing endpoint depends on the new tables in this change, rollout is additive and backward compatible.
