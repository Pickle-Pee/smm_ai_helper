# Tasks: Add durable marketing workflow persistence

## 1. Database models

- [ ] 1.1 Add `MarketingRun` SQLAlchemy model with stable `run_id`, optional user ownership, workflow type, lifecycle fields, JSON input/state, error, and timestamps.
- [ ] 1.2 Add `MarketingArtifact` SQLAlchemy model with run ownership, stable artifact key, artifact type/step, JSON payload, and timestamps.
- [ ] 1.3 Add relationships without changing existing task/profile behavior.
- [ ] 1.4 Add the `(run_id, artifact_key)` uniqueness invariant and required indexes.

## 2. Alembic migration

- [ ] 2.1 Create a new migration from current head `20260711_0002`; do not edit prior migrations.
- [ ] 2.2 Create `marketing_runs` and `marketing_artifacts` with matching constraints/indexes.
- [ ] 2.3 Implement downgrade in dependency-safe reverse order.

## 3. Persistence service

- [ ] 3.1 Add `MarketingWorkflowPersistenceService.create_run`.
- [ ] 3.2 Add `get_run` and run-state update operations.
- [ ] 3.3 Add artifact upsert by `(run_id, artifact_key)`.
- [ ] 3.4 Add artifact lookup and deterministic artifact listing.
- [ ] 3.5 Keep commit ownership with the caller; service operations may flush but must not force independent commits.

## 4. Tests

- [ ] 4.1 Test creation/loading of a user-owned marketing run.
- [ ] 4.2 Test creation/loading of an anonymous marketing run.
- [ ] 4.3 Test lifecycle/current-step/state/error updates.
- [ ] 4.4 Test creating and retrieving an artifact.
- [ ] 4.5 Test re-persisting the same artifact key updates the logical artifact instead of creating a duplicate.
- [ ] 4.6 Test deterministic artifact listing.
- [ ] 4.7 Add/adjust model or migration assertions needed to cover constraints and relationships.

## 5. Verification

- [ ] 5.1 Run `python -m compileall app bot`.
- [ ] 5.2 Run `alembic upgrade head` against PostgreSQL.
- [ ] 5.3 Run `python -m pytest`.
- [ ] 5.4 Run `openspec validate --all --strict`.
- [ ] 5.5 Review the final diff and confirm no routers, Telegram handlers, existing endpoint contracts, or unrelated runtime behavior changed.
