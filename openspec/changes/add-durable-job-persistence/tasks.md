# Tasks: Add durable Job persistence

## 1. Completed pre-implementation reconciliation

- [x] 1.1 Verify the clean task branch is based exactly on fetched `origin/sale-ready` at `bcdbd509450dd9d391ef7eeebf34134887264838`, with no earlier durable-Job branch or change.
- [x] 1.2 Read the complete repository architecture, product/roadmap material, all current OpenSpec changes/shared specs, persistence models/services/tests, Alembic environment/history, and every Job/queue/worker/retry/idempotency/MarketingRun/MarketingArtifact reference.
- [x] 1.3 Verify the corrected local environment baseline, single Alembic head, Quality Gates foundation, Marketing Workflow Persistence foundation, and importable Module Registry identity.
- [x] 1.4 Reconcile exact Job ownership, schema, closed lifecycle, payload/result/error/time coherence, deletion rules, and explicit deferred reliability behavior.
- [x] 1.5 Reconcile the internal service API, typed errors, transaction/locking/failure behavior, one-revision migration plan, compatibility proof obligations, and complete out-of-scope boundary.
- [x] 1.6 Align only directly affected architecture/product/roadmap documentation and create the durable pre-implementation verification template without claiming implementation evidence.

## 2. SQLAlchemy model and table contract

- [ ] 2.1 Add `JobStatus` with exact members/values `pending`, `running`, `succeeded`, and `failed`; add no aliases or additional lifecycle values.
- [ ] 2.2 Add `Job` mapped to `jobs` with the exact identity, ownership, kind, status, payload, result, error, and lifecycle timestamp column names/types/nullability from the design.
- [ ] 2.3 Implement exact Python and server defaults for status, empty-object payload, `created_at`, and `updated_at`; keep every other server default absent as designed.
- [ ] 2.4 Use timezone-aware SQLAlchemy timestamp columns for Job only, without rewriting or changing existing naive timestamp columns.
- [ ] 2.5 Add `User.jobs` and `MarketingRun.jobs` relationships with user `SET NULL`, run `CASCADE`, passive-delete, and run delete-orphan behavior matching the approved ownership model.
- [ ] 2.6 Add exact `job_id`, `kind`, and optional `workflow_step` format/length checks with no trimming or normalization behavior.
- [ ] 2.7 Add exact exclusive-owner and workflow-step-requires-run checks.
- [ ] 2.8 Add exact status-membership, JSON-object, lifecycle-field-coherence, non-empty bounded failure-error, and timestamp-order checks.
- [ ] 2.9 Add only `ix_jobs_user_created_job`, `ix_jobs_run_created_job`, `ix_jobs_status_created_job`, and `ix_jobs_kind` beyond the primary-key index, with exact column order.
- [ ] 2.10 Verify model metadata has no unique constraint beyond `job_id` and no retry/attempt/lease/worker/idempotency/delivery/cancellation/timeout field or index.

## 3. Alembic migration

- [ ] 3.1 Re-check that `20260814_0003` remains the sole head immediately before generation; stop for reconciliation if it changed.
- [ ] 3.2 Create one new revision from that head (design proposes `20260825_0004`) without editing any existing migration.
- [ ] 3.3 Make upgrade create only `jobs` with the exact column SQL types, nullability, primary key, defaults, and server defaults.
- [ ] 3.4 Add the exact user `ON DELETE SET NULL` and MarketingRun `ON DELETE CASCADE` foreign keys and all named check constraints.
- [ ] 3.5 Create the four approved indexes in the exact order and with the exact indexed columns; add no queue/recovery policy index beyond the approved status index.
- [ ] 3.6 Implement deterministic downgrade by dropping only the four Job indexes in reverse order and then `jobs`.
- [ ] 3.7 Add revision-continuity/static operation assertions proving one parent/head and no alteration of `users`, `marketing_runs`, `marketing_artifacts`, or unrelated structures.
- [ ] 3.8 Add PostgreSQL upgrade/downgrade/re-upgrade migration coverage that preserves earlier schema/data and does not stamp, rewrite, or destroy unrelated history.

## 4. Job persistence service

- [ ] 4.1 Add `JobPersistenceError`, `InvalidJobDataError`, `JobNotFoundError`, and `IllegalJobTransitionError` with stable safe messages that do not include raw payload/error values.
- [ ] 4.2 Add exact validators for UUID-hex Job IDs, kind/step keys, mutually exclusive ownership, aware UTC instants, bounded non-empty failure errors, and recursive JSON-compatible dictionaries.
- [ ] 4.3 Defensively copy accepted payload/result dictionaries and reject non-string keys, unsupported containers/objects, bytes, NaN, and infinities before touching the session.
- [ ] 4.4 Implement `create_job` so it always constructs `pending`, supports run/user/system ownership, maps `payload_json=None` to `{}`, adds, flushes once, and returns the Job.
- [ ] 4.5 Implement `get_job` by primary key with `Job | None` not-found behavior and no flush/commit/rollback.
- [ ] 4.6 Implement `list_jobs_for_run` with no run existence pre-query and exact `created_at ASC, job_id ASC` ordering.
- [ ] 4.7 Implement transition loading with `SELECT ... FOR UPDATE`, then raise `JobNotFoundError` for an absent target.
- [ ] 4.8 Implement only `pending -> running`, setting `started_at`/`updated_at` and prohibiting result/error/completion fields.
- [ ] 4.9 Implement only `running -> succeeded`, requiring a result object, setting `completed_at`/`updated_at`, and prohibiting error.
- [ ] 4.10 Implement only `running -> failed`, requiring a bounded non-empty error, setting `completed_at`/`updated_at`, and prohibiting result.
- [ ] 4.11 Reject same-state, skipped, terminal, malformed-field, and backwards-time transitions before mutating or flushing the loaded Job.
- [ ] 4.12 Keep every mutation at add/flush only with zero autonomous commit or rollback; let duplicate/FK/check/database failures propagate for caller rollback.
- [ ] 4.13 Keep the service unused by current runtime paths and free of Redis, queue, worker, polling, scheduler, delivery, module/agent, Orchestrator/Quality-Gates execution, LLM/OpenAI, QC, image, URL, API, and Telegram dependencies or calls.

## 5. Independent model, service, transaction, and migration tests

- [ ] 5.1 Assert the complete Job table column set, SQL/Python types, nullability, lengths, application defaults, server defaults, and absence of unapproved columns.
- [ ] 5.2 Assert exact `JobStatus` membership/order/values and reject raw unsupported status strings or aliases at the service boundary.
- [ ] 5.3 Assert exact primary key, four indexes/column order, no extra uniqueness, and every named check expression/constraint.
- [ ] 5.4 Assert both foreign-key targets and delete actions plus User/MarketingRun relationship configuration.
- [ ] 5.5 Test run-owned, runless user-owned, and system/anonymous Job creation and reject dual ownership or runless workflow step.
- [ ] 5.6 Test generated and caller-supplied Job identifiers plus invalid length/case/character/empty values.
- [ ] 5.7 Test valid kind/step boundary lengths and reject empty, whitespace, uppercase, normalized-looking, or invalid-character values.
- [ ] 5.8 Test empty and nested JSON objects, defensive copying, and rejection of non-string keys, tuple/set/bytes/custom/non-finite values before session access.
- [ ] 5.9 Test `pending` creation field coherence, exact timestamps/defaults, one add/flush, and no commit/rollback.
- [ ] 5.10 Test `get_job` for existing and missing identifiers with no mutation or transaction ownership.
- [ ] 5.11 Test empty and populated run-scoped listing, run filter, and deterministic creation-time/Job-ID ordering.
- [ ] 5.12 Test each of the three legal lifecycle edges independently, including exact status/result/error/start/completion/update fields.
- [ ] 5.13 Test every illegal graph edge, same-state request, and terminal successor with typed error and zero Job mutation/flush.
- [ ] 5.14 Test success requires a JSON result and prohibits error; test failure requires a 1-4000 non-whitespace error and prohibits result.
- [ ] 5.15 Test timezone offsets normalize to UTC with microseconds preserved and reject naive/subclass/string/backwards timestamps.
- [ ] 5.16 Test transition SQL uses row locking and evaluates state only after the locked row is returned.
- [ ] 5.17 Add a PostgreSQL concurrency regression proving a second transition observes the first committed state and cannot apply a now-illegal transition.
- [ ] 5.18 Test duplicate primary-key, missing user/run FK, database check, and flush failures propagate without service commit/rollback and leave rollback ownership to the caller.
- [ ] 5.19 Add a PostgreSQL transaction regression proving flushed Job plus MarketingRun mutation commits atomically on success and both disappear/revert on caller rollback.
- [ ] 5.20 Test MarketingRun deletion cascades to owned Jobs and artifacts, while user deletion nulls runless Job ownership and preserves the Job.
- [ ] 5.21 Test migration upgrade reflection for every Job column/default/FK/check/index and unchanged earlier tables/data.
- [ ] 5.22 Test migration downgrade removes only Job structures, restores head `20260814_0003`, and deterministic re-upgrade recreates the exact contract.

## 6. Compatibility, isolation, and packaging evidence

- [ ] 6.1 Prove existing MarketingRun creation/update/status fields and MarketingArtifact upsert/unique/cascade/list behavior remain unchanged.
- [ ] 6.2 Prove `/chat`, `/tasks`, `/images`, `/brand-profile`, deprecated `/agents`, public schemas/result DTOs, presenters, and Telegram handlers have no contract or behavior change.
- [ ] 6.3 Prove `TaskRouter`, `AgentRunner`, `AgentRegistry`, and `TaskPipelineService` responsibilities, task state transitions, results, and call counts remain unchanged.
- [ ] 6.4 Prove Marketing Orchestrator planner/validator exact scenarios, identities, isolation, and `PLANNING_ONLY` readiness remain unchanged.
- [ ] 6.5 Prove Quality Gates contracts, fingerprints, evaluation/decision results, isolation, and `PLANNING_ONLY` readiness remain unchanged.
- [ ] 6.6 Re-verify Module Registry version `1.0.0`, 15 descriptors, zero bindings, and checksum `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`.
- [ ] 6.7 Add import/source isolation assertions proving no current router, Telegram handler, pipeline, workflow, agent, presenter, Orchestrator, or Quality Gates component imports or calls Job persistence.
- [ ] 6.8 Add fail-on-call fakes/source assertions proving zero Redis/queue/worker/polling/scheduler/delivery/module execution/LLM/OpenAI/QC/image/URL/external calls.
- [ ] 6.9 Confirm `requirements.txt`, dependency locks/manifests, Dockerfile, Docker Compose, CI workflow, environment variables, and package-resource behavior are unchanged.
- [ ] 6.10 Review the implementation diff and confirm only approved model/service/migration/test/evidence/task files changed, with no unrelated refactor.

## 7. Implementation verification and durable evidence

- [ ] 7.1 Run focused Job model/service/transaction tests with `.venv\Scripts\python.exe` and record exact pass/fail counts.
- [ ] 7.2 Run the PostgreSQL migration upgrade/downgrade/re-upgrade checks from the correct revisions and record exact results.
- [ ] 7.3 Run `.venv\Scripts\python.exe -m alembic heads` and prove the new revision is the sole head.
- [ ] 7.4 Run focused Marketing Workflow Persistence, Module Registry, Marketing Orchestrator, Quality Gates, task/pipeline, public API, and Telegram compatibility tests and record exact counts.
- [ ] 7.5 Run `.venv\Scripts\python.exe -m pytest -q` and record the exact full-suite count and warnings.
- [ ] 7.6 Run `.venv\Scripts\python.exe -m compileall app bot` and record the successful result.
- [ ] 7.7 Run `openspec validate add-durable-job-persistence --strict` and `openspec validate --all --strict` and record exact results.
- [ ] 7.8 Run `git diff --check origin/sale-ready...HEAD`, `git status --short`, and a path audit proving no unapproved runtime/test/migration/config file changed.
- [ ] 7.9 Complete `docs/development/durable-job-persistence-verification.md` with actual schema/lifecycle/transaction/migration/compatibility/isolation evidence; replace pending placeholders only with executed results.
- [ ] 7.10 Record files changed, migration revision/parent, exact commands/results, no-commit/rollback evidence, Docker/package impact, limitations, blockers, and manual PostgreSQL verification steps in the implementation report.
- [ ] 7.11 Leave Redis publication/recovery, worker claiming/execution, retries/backoff/dead letters, leases, idempotency/deduplication, ordering/concurrency policy, cancellation/timeouts, delivery, APIs/Telegram UX, module/Orchestrator/Quality Gates integration, and outbox design for separately reviewed changes.
