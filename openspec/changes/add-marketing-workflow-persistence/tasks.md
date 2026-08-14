# Tasks: Add durable marketing workflow persistence

## 1. Database models

- [x] 1.1 Add `MarketingRun` SQLAlchemy model with stable `run_id`, optional user ownership, workflow type, lifecycle fields, JSON input/state, error, and timestamps.
- [x] 1.2 Add `MarketingArtifact` SQLAlchemy model with run ownership, stable artifact key, artifact type/step, JSON payload, and timestamps.
- [x] 1.3 Add relationships without changing existing task/profile behavior.
- [x] 1.4 Add the `(run_id, artifact_key)` uniqueness invariant and required indexes.

## 2. Alembic migration

- [x] 2.1 Create a new migration from current head `20260711_0002`; do not edit prior migrations.
- [x] 2.2 Create `marketing_runs` and `marketing_artifacts` with matching constraints/indexes.
- [x] 2.3 Implement downgrade in dependency-safe reverse order.

## 3. Persistence service

- [x] 3.1 Add `MarketingWorkflowPersistenceService.create_run`.
- [x] 3.2 Add `get_run` and run-state update operations.
- [x] 3.3 Add artifact upsert by `(run_id, artifact_key)`.
- [x] 3.4 Add artifact lookup and deterministic artifact listing.
- [x] 3.5 Keep commit ownership with the caller; service operations may flush but must not force independent commits.

## 4. Tests

- [x] 4.1 Test creation/loading of a user-owned marketing run.
- [x] 4.2 Test creation/loading of an anonymous marketing run.
- [x] 4.3 Test lifecycle/current-step/state/error updates.
- [x] 4.4 Test creating and retrieving an artifact.
- [x] 4.5 Test re-persisting the same artifact key updates the logical artifact instead of creating a duplicate.
- [x] 4.6 Test deterministic artifact listing.
- [x] 4.7 Add/adjust model or migration assertions needed to cover constraints and relationships.

## 5. Verification

- [ ] 5.1 Run `python -m compileall app bot`.
- [ ] 5.2 Run `alembic upgrade head` against PostgreSQL.
- [ ] 5.3 Run `python -m pytest`.
- [ ] 5.4 Run `openspec validate --all --strict`.
- [ ] 5.5 Review the final diff and confirm no routers, Telegram handlers, existing endpoint contracts, or unrelated runtime behavior changed.
