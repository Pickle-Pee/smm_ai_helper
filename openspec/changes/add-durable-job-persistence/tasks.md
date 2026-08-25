# Tasks: Add durable Job persistence

## 1. Completed pre-implementation reconciliation

- [x] 1.1 Verify the clean task branch is based exactly on fetched `origin/sale-ready` at `bcdbd509450dd9d391ef7eeebf34134887264838`.
- [x] 1.2 Read repository architecture/product/roadmap material, persistence conventions, Alembic history, and relevant OpenSpec changes completely.
- [x] 1.3 Verify the corrected repository `.venv` baseline, sole Alembic head, Quality Gates, Marketing Workflow Persistence, and Module Registry identity.
- [x] 1.4 Reconcile the Job/MarketingRun/MarketingArtifact responsibility boundary and persistence-only scope.
- [x] 1.5 Reconcile the closed lifecycle, transaction ownership, row locking, migration parent, compatibility, and deferred reliability behavior.
- [x] 1.6 Create aligned architecture/product/roadmap documentation and a pre-implementation verification template without implementation claims.
- [x] 1.7 Replace user `SET NULL` with aggregate-child `CASCADE`, define the ownership truth table, system authorization, and non-audit retention.
- [x] 1.8 Define exact loaded/unloaded ORM cascade and passive-delete behavior with no owner nullification.
- [x] 1.9 Scope immutability to supported persistence operations, define unsupported direct-session mutation, defensive copying, and callable JSON defaults.
- [x] 1.10 Publish every exact PostgreSQL predicate and matching Python/database responsibility.
- [x] 1.11 Define bounded canonical JSON, sanitized persisted errors, and producer security responsibilities.
- [x] 1.12 Remove caller creation/transition timestamps and define one injected UTC clock plus exact timestamp equalities/order.
- [x] 1.13 Define total validation precedence, no-refresh behavior, deliberate direct-user/system query absence, and the final two-index set.
- [x] 1.14 Split runtime/evidence tasks and correct Quality Gates documentation without changing runtime behavior.

## 2. SQLAlchemy model and relationship contract

- [ ] 2.1 Add `JobStatus` with exact ordered members/values `pending`, `running`, `succeeded`, and `failed` and no aliases.
- [ ] 2.2 Add `Job` mapped to `jobs` with exactly the thirteen approved columns and no others.
- [ ] 2.3 Add `job_id VARCHAR(32)` primary key with callable UUID-hex application generation and no server default.
- [ ] 2.4 Add nullable `user_id INTEGER` and `marketing_run_id VARCHAR(64)` owner columns with no application/server defaults beyond null.
- [ ] 2.5 Add nullable `workflow_step VARCHAR(64)` and required `kind VARCHAR(64)` with no normalization behavior.
- [ ] 2.6 Add `status VARCHAR(32)` with exact Python `pending` default and server default `'pending'`.
- [ ] 2.7 Add non-null `payload_json JSONB` with callable `default=dict`, server default `'{}'::jsonb`, and no shared object.
- [ ] 2.8 Add nullable `result_json JSONB` and nullable `error VARCHAR(4000)` with no server defaults.
- [ ] 2.9 Add timezone-aware `created_at` and `updated_at` with `server_default=now()` and no automatic update hook.
- [ ] 2.10 Add nullable timezone-aware `started_at` and `completed_at` without defaults.
- [ ] 2.11 Add `user_id -> users.id ON DELETE CASCADE` with matching SQL type/nullability.
- [ ] 2.12 Add `marketing_run_id -> marketing_runs.run_id ON DELETE CASCADE` with matching SQL type/nullability.
- [ ] 2.13 Add `User.jobs` with exact `back_populates`, `cascade="all, delete-orphan"`, and `passive_deletes=True`.
- [ ] 2.14 Add `MarketingRun.jobs` with exact `back_populates`, `cascade="all, delete-orphan"`, and `passive_deletes=True`.
- [ ] 2.15 Keep Job JSON columns free of `MutableDict` or any tracked-mutation wrapper.
- [ ] 2.16 Add only the run and status composite secondary indexes defined by the design.
- [ ] 2.17 Add no user or kind index and no unique constraint beyond the primary key.
- [ ] 2.18 Add no retry/attempt/lease/worker/idempotency/delivery/cancellation/timeout/audit field or index.

## 3. Exact constraints and Alembic operations

- [ ] 3.1 Re-check immediately before generation that `20260814_0003` remains the sole Alembic head.
- [ ] 3.2 Generate one new revision from that head, using proposed ID `20260825_0004` only if still available.
- [ ] 3.3 Make upgrade create only `jobs` with the exact columns, types, nullability, defaults, primary key, and two foreign keys.
- [ ] 3.4 Implement `ck_jobs_job_id_format` with exact predicate `job_id ~ '^[0-9a-f]{32}$'`.
- [ ] 3.5 Implement `ck_jobs_kind_format` with the exact canonical-key regex predicate.
- [ ] 3.6 Implement `ck_jobs_workflow_step_format` with the exact nullable canonical-key predicate.
- [ ] 3.7 Implement `ck_jobs_exclusive_owner` with exact predicate `marketing_run_id IS NULL OR user_id IS NULL`.
- [ ] 3.8 Implement `ck_jobs_step_requires_run` with exact predicate `workflow_step IS NULL OR marketing_run_id IS NOT NULL`.
- [ ] 3.9 Implement `ck_jobs_status` with exactly the four approved status strings.
- [ ] 3.10 Implement `ck_jobs_payload_object` with exact `jsonb_typeof(payload_json) = 'object'` predicate.
- [ ] 3.11 Implement `ck_jobs_result_object` with the exact nullable JSON-object predicate.
- [ ] 3.12 Implement `ck_jobs_lifecycle` with the complete four-branch predicate and matching ASCII-whitespace failure rule.
- [ ] 3.13 Implement `ck_jobs_timestamp_order` with all creation/start/completion ordering and status-specific update equalities.
- [ ] 3.14 Create `ix_jobs_run_created_job` on exact ascending columns `(marketing_run_id, created_at, job_id)`.
- [ ] 3.15 Create `ix_jobs_status_created_job` on exact ascending columns `(status, created_at, job_id)`.
- [ ] 3.16 Implement downgrade by dropping status index, run index, and then `jobs`, in that order only.
- [ ] 3.17 Add static revision-parent/head assertions with no alteration of existing tables, migrations, constraints, or indexes.
- [ ] 3.18 Keep every existing migration byte-for-byte unchanged.

## 4. Validation and persistence service implementation

- [ ] 4.1 Add the exact six-class Job persistence error taxonomy and stable safe messages without raw values.
- [ ] 4.2 Add an injected callable clock with an aware UTC production default and exact-type validation.
- [ ] 4.3 Validate Job IDs as exact built-in lowercase 32-character UUID-hex strings.
- [ ] 4.4 Validate kind and workflow step as exact built-in canonical-key strings with no trimming/normalization.
- [ ] 4.5 Validate MarketingRun IDs as exact built-in valid-Unicode strings of 1-64 characters excluding U+0000 and without normalization.
- [ ] 4.6 Validate user IDs as exact positive built-in integers and reject booleans.
- [ ] 4.7 Validate exact JSON dictionaries/lists/scalars and signed 64-bit integer bounds.
- [ ] 4.8 Detect JSON cycles using the active recursion path while allowing repeated acyclic references.
- [ ] 4.9 Enforce maximum JSON container depth 16 with top-level object at depth 1.
- [ ] 4.10 Reject lone surrogates, U+0000, and all JSON strings/keys that fail strict UTF-8/PostgreSQL compatibility.
- [ ] 4.11 Implement exact deterministic canonical JSON serialization for byte measurement.
- [ ] 4.12 Enforce 262,144-byte payload and 1,048,576-byte result limits with typed size errors.
- [ ] 4.13 Defensively deep-copy validated JSON before any session access or await.
- [ ] 4.14 Validate caller-sanitized errors as exact Unicode strings of 1-4000 characters with the exact ASCII-whitespace rule.
- [ ] 4.15 Reject exception objects, automatic stringification, traceback capture, and raw provider-response persistence.
- [ ] 4.16 Validate the four-row ownership truth table and workflow-step/run coherence before session access.
- [ ] 4.17 Query an explicitly supplied owner with autoflush disabled and reject a valid missing owner before clock acquisition.
- [ ] 4.18 Implement `create_job` in the exact ten-step order, assigning one clock instant to creation/update and flushing once.
- [ ] 4.19 Implement malformed-ID validation and valid-missing `None` behavior for `get_job` with no autoflush/lock/refresh.
- [ ] 4.20 Implement `list_jobs_for_run` validation, no run pre-query, empty-missing result, and exact unbounded ordering.
- [ ] 4.21 Keep direct-user/system listing, pagination, generic filtering, and generic mutation absent.
- [ ] 4.22 Prevalidate transition ID, exact status, outcome presence, result JSON, and error input before session access.
- [ ] 4.23 Load transition target with autoflush disabled, `SELECT ... FOR UPDATE`, and `populate_existing`.
- [ ] 4.24 Raise typed not-found only after pure input validation and before locked-state legality processing.
- [ ] 4.25 Evaluate the complete legal-transition graph only after the persisted row is locked/reloaded.
- [ ] 4.26 Obtain one transition clock instant after legality and apply exact UTC/order validation.
- [ ] 4.27 Apply only approved lifecycle/outcome fields and validate final coherence before one explicit flush.
- [ ] 4.28 Pass duplicate/FK/check/driver/database errors through unchanged for caller rollback.
- [ ] 4.29 Prohibit every autonomous commit, rollback, refresh, and implicit autoflush owned by the service.
- [ ] 4.30 Keep the service unused by current runtime paths and free of Redis/queue/worker/LLM/QC/API/Telegram dependencies.

## 5. Independent model and service evidence

- [ ] 5.1 Assert the exact thirteen-column set, SQL/Python types, lengths, and nullability.
- [ ] 5.2 Assert exact `JobStatus` order/values and rejection of raw strings/aliases at the service boundary.
- [ ] 5.3 Assert callable UUID/payload defaults, independent empty payload objects, and exact server defaults.
- [ ] 5.4 Assert timezone-aware Job timestamp columns without changing existing naive timestamp columns.
- [ ] 5.5 Test loaded User deletion deletes direct-user Jobs without owner-nullifying updates.
- [ ] 5.6 Test unloaded User deletion relies on PostgreSQL cascade with the same final rows.
- [ ] 5.7 Test loaded MarketingRun deletion deletes owned Jobs and preserves existing artifact cascade behavior.
- [ ] 5.8 Test unloaded MarketingRun deletion relies on PostgreSQL cascade with the same final rows.
- [ ] 5.9 Test removing a Job from either aggregate relationship deletes it instead of producing a system Job.
- [ ] 5.10 Test valid run-owned creation and optional workflow step.
- [ ] 5.11 Test valid direct-user-owned creation and prohibited workflow step.
- [ ] 5.12 Test valid trusted-internal system creation with both owners absent.
- [ ] 5.13 Test dual-owner rejection before owner query/add/flush.
- [ ] 5.14 Test runless workflow-step rejection before owner query/add/flush.
- [ ] 5.15 Test generated and valid caller-supplied Job IDs plus duplicate-ID propagation.
- [ ] 5.16 Test Job-ID invalid length, case, characters, empty value, subclass, and non-string input.
- [ ] 5.17 Test kind/workflow-step boundary lengths and invalid whitespace/case/characters/subclasses.
- [ ] 5.18 Test payload/result require exact top-level dictionaries.
- [ ] 5.19 Test JSON object keys require exact valid-Unicode strings.
- [ ] 5.20 Test exact scalar types, signed 64-bit integer boundaries, and boolean/int distinction.
- [ ] 5.21 Test rejection of tuples, sets, bytes, custom mappings/sequences, subclasses, and objects.
- [ ] 5.22 Test rejection of NaN, positive infinity, and negative infinity.
- [ ] 5.23 Test cycle rejection and acceptance of repeated acyclic references.
- [ ] 5.24 Test depth 16 acceptance and depth 17 rejection.
- [ ] 5.25 Test valid Unicode acceptance and lone-surrogate/U+0000 rejection in keys and values.
- [ ] 5.26 Test deterministic canonical JSON serialization and UTF-8 measurement.
- [ ] 5.27 Test payload size exactly at 262,144 bytes and one byte over.
- [ ] 5.28 Test result size exactly at 1,048,576 bytes and one byte over.
- [ ] 5.29 Test `payload_json=None` maps to a new empty object and empty result object is valid on success.
- [ ] 5.30 Test mutation of the caller's original payload/result after validation cannot alter persisted data.
- [ ] 5.31 Test scalar reassignment cannot persist through a supported transition.
- [ ] 5.32 Test complete payload reassignment cannot persist through a supported transition.
- [ ] 5.33 Test top-level in-place payload mutation cannot persist through a supported transition.
- [ ] 5.34 Test nested in-place payload mutation cannot persist through a supported transition.
- [ ] 5.35 Test/document unsupported direct-session mutation and absence of `MutableDict` or universal enforcement claims.
- [ ] 5.36 Test an approved sanitized failure error is preserved exactly and invalid Unicode/U+0000 is rejected.
- [ ] 5.37 Test empty and exact ASCII-whitespace-only errors are rejected in Python and PostgreSQL.
- [ ] 5.38 Test 4000-character error acceptance and 4001-character rejection without truncation.
- [ ] 5.39 Test exception/custom-object error rejection with no `str()` or traceback/provider conversion.
- [ ] 5.40 Add source/document evidence that producers own redaction and the service performs no automatic secret detection.
- [ ] 5.41 Test creation calls the injected clock exactly once and sets `created_at = updated_at`.
- [ ] 5.42 Test creation normalizes timezone offsets to UTC while preserving microseconds.
- [ ] 5.43 Test naive, datetime-subclass, string, and invalid clock return rejection before add/flush.
- [ ] 5.44 Test exact pending creation coherence, one add/flush, no refresh/commit/rollback.
- [ ] 5.45 Test malformed `get_job` ID raises before query.
- [ ] 5.46 Test `get_job` existing and valid-missing results with no lock/flush/refresh.
- [ ] 5.47 Test run listing filter/order, valid-missing empty result, no run pre-query, lock, pagination, or refresh.
- [ ] 5.48 Test legal `pending -> running` independently with exact outcome/timestamp fields.
- [ ] 5.49 Test legal `running -> succeeded` independently with exact result/timestamp fields.
- [ ] 5.50 Test legal `running -> failed` independently with exact error/timestamp fields.
- [ ] 5.51 Test skipped `pending -> succeeded` rejection independently.
- [ ] 5.52 Test skipped `pending -> failed` rejection independently.
- [ ] 5.53 Test backward `running -> pending` rejection independently.
- [ ] 5.54 Test `pending -> pending` same-state rejection independently.
- [ ] 5.55 Test `running -> running` same-state rejection independently.
- [ ] 5.56 Test `succeeded -> succeeded` same-state rejection independently.
- [ ] 5.57 Test `failed -> failed` same-state rejection independently.
- [ ] 5.58 Test terminal `succeeded -> pending` rejection independently.
- [ ] 5.59 Test terminal `succeeded -> running` rejection independently.
- [ ] 5.60 Test terminal `succeeded -> failed` rejection independently.
- [ ] 5.61 Test terminal `failed -> pending` rejection independently.
- [ ] 5.62 Test terminal `failed -> running` rejection independently.
- [ ] 5.63 Test terminal `failed -> succeeded` rejection independently.
- [ ] 5.64 Test success result-required/error-prohibited input precedence before database access.
- [ ] 5.65 Test failure error-required/result-prohibited input precedence before database access.
- [ ] 5.66 Test running transition prohibits result/error before database access.
- [ ] 5.67 Test running timestamp equality/order with one post-lock clock call.
- [ ] 5.68 Test successful terminal timestamp equality/order with one post-lock clock call.
- [ ] 5.69 Test failed terminal timestamp equality/order with one post-lock clock call.
- [ ] 5.70 Test backwards start/completion time rejection with zero mutation/explicit flush.
- [ ] 5.71 Test pure invalid input takes precedence over missing target and performs no query.
- [ ] 5.72 Test valid missing target takes precedence over illegal-state/clock processing.
- [ ] 5.73 Test every illegal edge leaves the Job unchanged with zero clock call/explicit flush.
- [ ] 5.74 Test transition SQL locks the exact primary-key row and evaluates state after lock acquisition.
- [ ] 5.75 Test persisted-row reload discards unsupported dirty immutable state before lifecycle mutation.

## 6. PostgreSQL migration, constraint, transaction, and concurrency evidence

- [ ] 6.1 Add an isolated/serial PostgreSQL migration fixture that restores the starting revision even on failure.
- [ ] 6.2 Test upgrade from `20260814_0003` preserves seeded earlier tables and rows.
- [ ] 6.3 Test reflected Job columns, types, nullability, defaults, primary key, and absence of unapproved columns.
- [ ] 6.4 Test `ck_jobs_job_id_format` independently with accepted/rejected rows.
- [ ] 6.5 Test `ck_jobs_kind_format` independently with accepted/rejected rows.
- [ ] 6.6 Test `ck_jobs_workflow_step_format` independently with accepted/rejected rows.
- [ ] 6.7 Test `ck_jobs_exclusive_owner` independently against all four truth-table rows.
- [ ] 6.8 Test `ck_jobs_step_requires_run` independently with accepted/rejected rows.
- [ ] 6.9 Test `ck_jobs_status` independently with all valid/invalid values.
- [ ] 6.10 Test `ck_jobs_payload_object` independently with object and non-object JSONB.
- [ ] 6.11 Test `ck_jobs_result_object` independently with null/object/non-object JSONB.
- [ ] 6.12 Test `ck_jobs_lifecycle` independently for each valid status branch and incoherent field combination.
- [ ] 6.13 Test `ck_jobs_timestamp_order` independently for every equality/order rule and reversed timestamp.
- [ ] 6.14 Test exact user and MarketingRun FK targets plus both `ON DELETE CASCADE` actions.
- [ ] 6.15 Test exact run/status index names, ascending column order, and absence of user/kind indexes.
- [ ] 6.16 Test downgrade removes only Job indexes/table and returns exactly to `20260814_0003`.
- [ ] 6.17 Test deterministic re-upgrade recreates the identical reflected contract.
- [ ] 6.18 Test revision continuity and prove the new revision is the sole head independently.
- [ ] 6.19 Test duplicate primary-key failure propagates with zero service commit/rollback.
- [ ] 6.20 Test missing-owner FK race/failure propagates with zero service commit/rollback.
- [ ] 6.21 Test check/driver flush failure propagates with rollback ownership left to the caller.
- [ ] 6.22 Test Job plus MarketingRun/Artifact mutations commit atomically in one caller transaction.
- [ ] 6.23 Test caller rollback removes/reverts flushed Job plus MarketingRun/Artifact mutations together.
- [ ] 6.24 Test concurrent transition makes the waiter observe committed state and reject a now-illegal edge.

## 7. Compatibility and isolation evidence

- [ ] 7.1 Prove MarketingRun creation/update/status behavior remains unchanged.
- [ ] 7.2 Prove MarketingArtifact upsert/uniqueness/cascade/list behavior remains unchanged.
- [ ] 7.3 Prove `TaskPipelineService` responsibilities, state transitions, results, and call counts remain unchanged.
- [ ] 7.4 Prove `TaskRouter` behavior and call counts remain unchanged.
- [ ] 7.5 Prove `AgentRunner` behavior and call counts remain unchanged.
- [ ] 7.6 Prove `AgentRegistry` identities and supported agents remain unchanged.
- [ ] 7.7 Prove Marketing Orchestrator scenarios, graphs, identities, isolation, and `PLANNING_ONLY` readiness remain unchanged.
- [ ] 7.8 Prove Quality Gates contracts, fingerprints, evaluation/decision outputs, isolation, and `PLANNING_ONLY` readiness remain unchanged.
- [ ] 7.9 Re-verify Module Registry version `1.0.0`, 15 descriptors, zero bindings, and checksum `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`.
- [ ] 7.10 Prove `/chat`, `/tasks`, `/images`, `/brand-profile`, and deprecated `/agents` contracts remain unchanged.
- [ ] 7.11 Prove public schemas/result DTOs and presenters remain unchanged.
- [ ] 7.12 Prove Telegram handlers, callback behavior, and backend mappings remain unchanged.
- [ ] 7.13 Prove requirements, locks/manifests, and package resources remain unchanged.
- [ ] 7.14 Prove Dockerfile, Compose, CI, environment variables, and configuration remain unchanged.
- [ ] 7.15 Add independent fail-on-call/source evidence for zero Redis calls/configuration.
- [ ] 7.16 Add independent fail-on-call/source evidence for zero worker/queue/polling/scheduler calls.
- [ ] 7.17 Add independent fail-on-call/source evidence for zero LLM/OpenAI calls.
- [ ] 7.18 Add independent fail-on-call/source evidence for zero model-based `QCService` calls.
- [ ] 7.19 Add independent source/call-count evidence that `TaskPipelineService` never imports/calls Job persistence.
- [ ] 7.20 Add independent evidence for zero autonomous persistence commit/rollback/refresh.
- [ ] 7.21 Add independent source/call-count evidence for zero API/Telegram Job calls.
- [ ] 7.22 Add independent fail-on-call/source evidence for zero URL/image/provider/external calls.
- [ ] 7.23 Prove no current workflow, agent, presenter, Orchestrator, or Quality Gates component imports Job persistence.
- [ ] 7.24 Review the implementation diff and prove only approved model/service/migration/test/evidence/task files changed.

## 8. Implementation verification and durable evidence

- [ ] 8.1 Run focused Job model/default/relationship tests with the repository `.venv` and record exact results.
- [ ] 8.2 Run focused Job validator/service/lifecycle/immutability tests and record exact results.
- [ ] 8.3 Run focused PostgreSQL constraint/transaction/concurrency tests and record exact results.
- [ ] 8.4 Run migration upgrade verification from `20260814_0003` and record exact results.
- [ ] 8.5 Run migration downgrade verification independently and record exact results.
- [ ] 8.6 Run deterministic migration re-upgrade verification independently and record exact results.
- [ ] 8.7 Run `.venv\Scripts\python.exe -m alembic heads` and prove the new revision is the sole head.
- [ ] 8.8 Run focused Marketing Workflow Persistence, Registry, Orchestrator, Quality Gates, pipeline, API, and Telegram compatibility tests.
- [ ] 8.9 Run `.venv\Scripts\python.exe -m pytest -q` and record exact pass/warning counts.
- [ ] 8.10 Run `.venv\Scripts\python.exe -m compileall app bot` and record success.
- [ ] 8.11 Run strict change OpenSpec validation and record success.
- [ ] 8.12 Run strict all-artifact OpenSpec validation and record exact totals.
- [ ] 8.13 Run branch diff-check, final status, and prohibited-path audit independently.
- [ ] 8.14 Complete `docs/development/durable-job-persistence-verification.md` only with executed schema/lifecycle/security/transaction/migration/compatibility evidence.
- [ ] 8.15 Record files changed, revision/parent, commands/results, no-commit/rollback evidence, packaging impact, limitations, blockers, and manual PostgreSQL steps.
- [ ] 8.16 Leave publication/recovery, workers, retries/idempotency, leases, cancellation/timeouts, delivery, APIs/Telegram UX, execution integration, and outbox design for separate changes.
