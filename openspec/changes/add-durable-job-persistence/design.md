# Design: Durable Job persistence

## Context

See `proposal.md` for motivation and `specs/durable-job-persistence/spec.md` for normative behavior.

The current persistence foundation has `MarketingRun` for one multi-step workflow's progress and `MarketingArtifact` for named durable outputs. `MarketingWorkflowPersistenceService` adds/updates/flushes without committing so a caller can atomically advance a run and store an artifact. No current component creates or executes Jobs. The Marketing Orchestrator remains deterministic `PLANNING_ONLY`; Quality Gates remain pure; Module Registry `1.0.0` has 15 metadata-only descriptors and zero bindings.

PostgreSQL is the durable source of truth. Redis is absent and remains future transport/coordination only. Current public flows use `TaskPipelineService`, current routers/Telegram handlers, and their existing transaction behavior; this design does not connect Job persistence to any of them.

The authoritative implementation base is `bcdbd509450dd9d391ef7eeebf34134887264838`. Alembic has one head, `20260814_0003`, which created `marketing_runs` and `marketing_artifacts`.

## Goals / Non-Goals

**Goals:**

- Define one exact additive PostgreSQL Job contract and closed lifecycle.
- Keep Job, MarketingRun, and MarketingArtifact responsibilities non-overlapping.
- Permit later application/workflow code to create a Job atomically with related workflow-state changes.
- Make transition concurrency and transaction ownership explicit before workers exist.
- Make schema, lifecycle, service, migration, failure, compatibility, and evidence obligations independently testable.

**Non-Goals:**

- No Redis/queue dependency, publication, worker claim/execution, polling, scheduler, module invocation, delivery, or workflow-engine integration.
- No retry/backoff/dead-letter policy, attempts, leases, heartbeats, worker identity, idempotency key/deduplication, per-user ordering, concurrency limits, cancellation, or timeout enforcement.
- No outbox, API/Telegram surface, LLM/OpenAI/QC call, new public DTO, or change to current synchronous behavior.
- No generic repository abstraction and no refactor of existing persistence services.

## Decisions

### 1. Job owns a work request, not workflow progress or output

A Job represents one durable request for future asynchronous work. It owns immutable request identity/input plus its own execution lifecycle. It does not own a workflow plan, current workflow state, or reusable business output:

| Aggregate | Responsibility |
| --- | --- |
| `MarketingRun` | Multi-step workflow identity, current step, workflow state, and workflow-level failure/progress |
| `MarketingArtifact` | Named structured output consumable by workflow steps |
| `Job` | One requested execution unit, its input, state, result/error, and lifecycle times |

The same data is not copied between these aggregates merely for convenience. A Job payload may contain references/inputs needed by later execution, but it does not replace `MarketingRun.state_json`; a successful Job result does not replace a durable `MarketingArtifact`. A future workflow unit may atomically transition the Job and separately upsert the artifact/run state in one caller transaction.

Ownership is explicit without a polymorphic owner column:

- `marketing_run_id` set, `user_id` null: the MarketingRun owns the Job; optional `workflow_step` names the stable run step. Deleting the run cascades to these Jobs.
- `marketing_run_id` null, `user_id` set: the user owns a runless Job. Deleting the user sets `user_id` null so the durable record survives.
- both null: system/anonymous runless Job.
- both set is invalid. A workflow step without a run is invalid.

A Job can therefore exist without a MarketingRun. It does not belong directly to a Module Registry descriptor: `kind` names the work contract as validated opaque persistence metadata, while module selection/binding/execution remains a later reviewed contract. There is no `module_id` column or Registry foreign key.

No current component is authorized or wired to create or transition Jobs. A future reviewed `MarketingWorkflowService` may create run-owned Jobs through the persistence service. A future reviewed worker/claim boundary may lock/claim and execute them. Those integrations must not bypass this lifecycle contract.

**Alternatives rejected:** making Job another MarketingRun status duplicates workflow state; storing outputs only on Job duplicates MarketingArtifact; requiring every Job to have a run prevents legitimate later runless work; generic `owner_type/owner_id` loses referential integrity; simultaneous run and user ownership permits drift.

### 2. Exact `jobs` table contract

The table name is `jobs`. SQLAlchemy stores `JobStatus` values as strings in `VARCHAR`, not as a PostgreSQL enum type, matching repository string-status practice while the check constraint closes membership. `JobStatus` is a Python `str, Enum` with exactly `pending`, `running`, `succeeded`, and `failed`.

| Column | SQL / Python type | Null | Application default | Server default | Owner / mutability |
| --- | --- | ---: | --- | --- | --- |
| `job_id` | `VARCHAR(32)` / `str` | no | `uuid.uuid4().hex` | none | Job identity; immutable |
| `user_id` | `INTEGER` / `int | None` | yes | `None` | none | Optional runless user owner; immutable except FK `SET NULL` |
| `marketing_run_id` | `VARCHAR(64)` / `str | None` | yes | `None` | none | Optional run owner; immutable |
| `workflow_step` | `VARCHAR(64)` / `str | None` | yes | `None` | none | Optional stable step of a run-owned Job; immutable |
| `kind` | `VARCHAR(64)` / `str` | no | none | none | Work-contract key; immutable |
| `status` | `VARCHAR(32)` / `JobStatus` | no | `pending` | `'pending'` | Mutable only through legal transition |
| `payload_json` | `JSONB` / `dict[str, JsonValue]` | no | empty object | `'{}'::jsonb` | Immutable request input after creation |
| `result_json` | `JSONB` / `dict[str, JsonValue] | None` | yes | `None` | none | Written exactly once on success |
| `error` | `VARCHAR(4000)` / `str | None` | yes | `None` | none | Written exactly once on failure |
| `created_at` | `TIMESTAMPTZ` / aware `datetime` | no | current UTC | `now()` | Creation time; immutable |
| `updated_at` | `TIMESTAMPTZ` / aware `datetime` | no | current UTC | `now()` | Set on each legal mutation |
| `started_at` | `TIMESTAMPTZ` / aware `datetime | None` | yes | `None` | none | Set on `pending -> running` |
| `completed_at` | `TIMESTAMPTZ` / aware `datetime | None` | yes | `None` | none | Set on transition to terminal |

`job_id` is a lowercase 32-character UUID-hex value. A caller-supplied identifier is allowed for deterministic integration/testing only if it satisfies the same exact contract; no trimming, case folding, or arbitrary external identifier is accepted.

`kind` and non-null `workflow_step` match `^[a-z][a-z0-9_.-]{0,63}$`. They are case-sensitive, not trimmed or normalized, and empty values are prohibited. This foundation does not close the set of kinds because executable work kinds do not yet exist; each future producer must define its supported kind outside this persistence substrate. `error` is an exact string of 1-4000 characters after whitespace-only rejection and is stored unchanged.

`payload_json` and non-null `result_json` must be exact built-in dictionaries with string keys and recursively JSON-compatible `None`, `bool`, `int`, finite `float`, `str`, list, and dictionary values. The service validates and defensively deep-copies them. Non-string keys, tuples/sets/bytes/custom objects, NaN, and infinities are rejected. Empty objects are valid. PostgreSQL checks `jsonb_typeof(...) = 'object'`; binary image content remains in image storage and only references/metadata belong in JSONB. JSONB has no artificial byte limit in this foundation; payload-growth monitoring and a product-specific size limit require evidence from later real job kinds.

Foreign keys and deletion:

- `user_id -> users.id ON DELETE SET NULL`;
- `marketing_run_id -> marketing_runs.run_id ON DELETE CASCADE`.

There are no unique constraints beyond the primary key and no update/delete behavior on existing tables. Relationships will be `User.jobs` for runless user ownership and `MarketingRun.jobs` for run ownership; the run relationship uses delete-orphan/passive-delete behavior consistent with `MarketingRun.artifacts` and the database cascade.

Exact named checks:

- `ck_jobs_job_id_format`: `job_id` is exactly 32 lowercase hexadecimal characters.
- `ck_jobs_kind_format`: `kind` matches the key grammar.
- `ck_jobs_workflow_step_format`: step is null or matches the key grammar.
- `ck_jobs_exclusive_owner`: `marketing_run_id` and `user_id` are not both non-null.
- `ck_jobs_step_requires_run`: `workflow_step IS NULL OR marketing_run_id IS NOT NULL`.
- `ck_jobs_status`: status is one of the four exact values.
- `ck_jobs_payload_object`: payload is a JSON object.
- `ck_jobs_result_object`: result is null or a JSON object.
- `ck_jobs_lifecycle`: state-specific timestamp/result/error coherence defined below, including non-empty failure error.
- `ck_jobs_timestamp_order`: `updated_at >= created_at`, `started_at IS NULL OR started_at >= created_at`, and `completed_at IS NULL OR (started_at IS NOT NULL AND completed_at >= started_at)`.

Exact indexes:

- primary-key index on `job_id`;
- `ix_jobs_user_created_job` on `(user_id, created_at, job_id)`;
- `ix_jobs_run_created_job` on `(marketing_run_id, created_at, job_id)`;
- `ix_jobs_status_created_job` on `(status, created_at, job_id)`;
- `ix_jobs_kind` on `(kind)`.

The status index supports later bounded recovery/query design without defining polling or claiming behavior now. No queue/lease/attempt/idempotency columns or indexes are present.

### 3. Closed lifecycle and field matrix

The transition graph is exact:

```text
pending -> running -> succeeded
                   \-> failed
```

| Status | Meaning | Legal predecessors | Legal successors | Required | Prohibited | Terminal |
| --- | --- | --- | --- | --- | --- | ---: |
| `pending` | Durably accepted, not started or claimed | creation only | `running` | payload, created/updated | started/completed/result/error | no |
| `running` | Future executor has started the unit | `pending` | `succeeded`, `failed` | payload, started, created/updated | completed/result/error | no |
| `succeeded` | Work completed with a structured result | `running` | none | payload, started/completed, result, created/updated | error | yes |
| `failed` | Work completed unsuccessfully with diagnostic error | `running` | none | payload, started/completed, non-empty error, created/updated | result | yes |

Creation always produces `pending`; callers cannot create historical `running` or terminal rows through the service. Same-state transitions, terminal transitions, skipping `running`, missing/extra result/error fields, and backwards timestamps raise `IllegalJobTransitionError` or `InvalidJobDataError` before mutation/flush. A transition failure does not silently coerce fields or repair a malformed row.

The transition timestamp is an exact timezone-aware `datetime`, normalized to UTC while preserving microseconds. The service accepts an explicit timestamp for deterministic callers/tests; omission uses current aware UTC application time. `started_at` is set only on start. `completed_at` is set only on terminal transition. `updated_at` equals the transition instant. Created/start/completion ordering is checked in the service and database.

There is deliberately no `cancelled`, `retrying`, `scheduled`, `timed_out`, `dead_lettered`, or delivery state. Adding one changes the lifecycle contract and requires a later OpenSpec revision and migration if needed.

### 4. Internal persistence service boundary

Future runtime ownership is `app/services/job_persistence_service.py` with `JobPersistenceService` and its narrow error taxonomy. The SQLAlchemy `Job` model and `JobStatus` live with other durable models in `app/models.py`. No router, Telegram handler, Orchestrator, Quality Gates, agent, presenter, or pipeline imports the service in this change.

Exact operations:

```text
create_job(
    db_session: AsyncSession,
    *,
    kind: str,
    payload_json: dict[str, JsonValue] | None = None,
    user_id: int | None = None,
    marketing_run_id: str | None = None,
    workflow_step: str | None = None,
    job_id: str | None = None,
    created_at: datetime | None = None,
) -> Job

get_job(db_session: AsyncSession, job_id: str) -> Job | None

list_jobs_for_run(
    db_session: AsyncSession,
    marketing_run_id: str,
) -> list[Job]

transition_job(
    db_session: AsyncSession,
    job_id: str,
    to_status: JobStatus,
    *,
    result_json: dict[str, JsonValue] | None = None,
    error: str | None = None,
    occurred_at: datetime | None = None,
) -> Job
```

`payload_json=None` means the valid empty object, not SQL null. `result_json` is required exactly for `succeeded` and prohibited otherwise; `error` is required exactly for `failed` and prohibited otherwise. `create_job` validates/copies data, adds, and flushes once. `transition_job` loads by primary key with `SELECT ... FOR UPDATE`, validates the post-lock current state, mutates, and flushes once. `get_job` returns `None` for absence. `list_jobs_for_run` returns an empty list when no rows match and orders by `created_at ASC, job_id ASC`; it does not first validate that a run exists. Read methods do not flush.

Error taxonomy:

- `JobPersistenceError`: base domain error.
- `InvalidJobDataError`: invalid identifier/key/owner/JSON/error/timestamp input.
- `JobNotFoundError`: transition target is absent.
- `IllegalJobTransitionError`: requested predecessor/successor or field combination is illegal.

Database failures such as foreign-key violations and duplicate primary keys propagate as SQLAlchemy/database exceptions from `flush`; they are not ambiguously reclassified. The session is then caller-owned and may require rollback. Duplicate `job_id` produces no second committed row. This foundation has no idempotency/deduplication behavior: resubmitting semantic work under a different ID creates a different Job.

The row lock is transition serialization, not a worker claim or lease. It is held until the caller commits/rolls back. If concurrent transitions wait, the later transaction evaluates the newly committed state and either performs its still-legal transition or receives `IllegalJobTransitionError`. Lock timeouts and deadlock retry policy remain caller/infrastructure concerns for a later worker change.

**Alternatives rejected:** autonomous commits prevent atomic workflow updates; pre-query duplicate detection races; a generic list/filter/claim API encourages database polling before worker design; optimistic version fields and leases introduce worker/concurrency policy outside this foundation.

### 5. Transaction, failure, and durability semantics

The rule is unchanged from `MarketingWorkflowPersistenceService`:

```text
service may add/flush
service does not commit or roll back
caller owns transaction boundaries
```

A future caller can use one `AsyncSession` transaction for Job creation/transition plus MarketingRun/MarketingArtifact mutations. Flush establishes database validity and identifiers but is not durability. Durability begins only after the caller commits PostgreSQL. If any flush or later operation fails, the exception propagates and the caller rolls back the entire unit; the service never attempts an independent compensating write.

This prevents partial PostgreSQL writes within one caller transaction. It does not provide atomicity between PostgreSQL and a future Redis publication. Before Redis exists, a committed `pending` Job is durable but inert. After queue integration, crash recovery, publication gaps, at-least/at-most-once execution, idempotency, and reconciliation require a separately approved design. No outbox is introduced or implied here.

### 6. Migration contract

Plan one new Alembic revision, proposed ID `20260825_0004`, with exact parent `20260814_0003`. The actual apply step must re-check that this remains the sole current head before generating the revision; if the head changed, reconciliation is required rather than creating a branch head.

Upgrade operations, in order:

1. create `jobs` with only the approved columns, primary key, foreign keys, and named checks;
2. create `ix_jobs_user_created_job`;
3. create `ix_jobs_run_created_job`;
4. create `ix_jobs_status_created_job`;
5. create `ix_jobs_kind`.

Downgrade drops those indexes in reverse order and then drops `jobs`. It does not modify `users`, `marketing_runs`, `marketing_artifacts`, existing indexes/constraints, or historical data. The initial baseline migration's intentionally empty downgrade remains untouched.

Migration verification must cover revision metadata/continuity, offline/static operation shape, PostgreSQL upgrade from `20260814_0003` to the new head, exact reflected table/column/default/FK/check/index contract, downgrade one revision, absence of `jobs`, survival of all earlier tables/data, and re-upgrade determinism. Tests must not rewrite or stamp unrelated history.

### 7. Compatibility and isolation

The later implementation diff must leave these contracts and call paths unchanged:

- `/chat`, `/tasks`, `/images`, `/brand-profile`, deprecated `/agents`, and Telegram handlers;
- `TaskPipelineService`, `TaskRouter`, `AgentRunner`, `AgentRegistry`, agents, presenters, and public schemas/result DTOs;
- `MarketingWorkflowPersistenceService`, MarketingRun status semantics, MarketingArtifact upsert/uniqueness/cascade/list order;
- Marketing Orchestrator planner/validator scenarios, identities, and `PLANNING_ONLY` readiness;
- Quality Gates contracts/evaluation/fingerprints/decisions;
- Module Registry resource `1.0.0`, descriptor count 15, zero bindings, and checksum `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`;
- existing LLM/OpenAI/QC call counts and Docker/package dependencies/configuration.

Isolation tests/source inspection must prove Job persistence makes zero Redis, queue, worker, polling, scheduler, delivery, agent, module, Orchestrator-execution, Quality-Gates-execution, LLM/OpenAI, QC, URL, image, API, or Telegram calls. No endpoint or current runtime service calls the new persistence service.

### 8. Expected implementation and evidence files

Future implementation is expected to touch only:

- `app/models.py`;
- `app/services/job_persistence_service.py`;
- `migrations/versions/20260825_0004_durable_job_persistence.py` (subject to head re-check);
- focused Job model/service/migration tests;
- this change's task state and the durable verification document after evidence exists.

Directly aligned product/architecture documentation may be updated, but runtime code outside these areas, dependency manifests, Docker/CI configuration, routers, bot code, existing migrations, and unrelated tests remain untouched.

## Risks / Trade-offs

- [A committed pending Job is mistaken for enqueued work] -> documentation and APIs call it durable-but-inert until a later queue integration; no current caller is wired.
- [String kind is mistaken for executable registration] -> validate syntax only and require each future producer/worker contract to define supported kinds.
- [No idempotency permits semantic duplicates] -> stable primary keys prevent only identifier duplicates; semantic deduplication is explicitly deferred to `add-job-retries-and-idempotency`.
- [PostgreSQL/Redis publication gap remains] -> do not claim cross-system atomicity and do not silently add an outbox; solve in a reviewed queue/recovery change.
- [Cascade deletion removes run-owned Job history] -> run ownership deliberately matches MarketingArtifact aggregate deletion; user-owned runless Jobs survive user deletion.
- [JSONB can grow] -> store structured metadata only, never binaries; add evidence-based product limits with real work kinds later.
- [Row locks can wait/deadlock] -> keep transactions short and caller-owned; worker lock timeout/retry policy is out of scope.
- [Timezone-aware Job columns differ from older naive columns] -> make Job semantics explicit and test PostgreSQL round trips; do not rewrite older timestamps.

## Migration Plan

1. Re-check clean branch, single Alembic head, and accepted OpenSpec artifacts before implementation.
2. Add the model/status and focused contract tests.
3. Generate one migration from the then-current single head and reconcile its operations to this exact contract.
4. Add the persistence service and lifecycle/transaction/concurrency tests without wiring a caller.
5. Verify upgrade/downgrade/re-upgrade on PostgreSQL, focused compatibility/isolation, full tests, compilation, and strict OpenSpec validation.
6. Deploy the additive migration before any later code is authorized to create Jobs.

Rollback before dependent changes is one-revision Alembic downgrade followed by code revert. A later dependent migration or live Job data requires a separately reviewed rollback/data-retention plan; this foundation does not silently delete production Jobs.

There are no remaining pre-implementation design blockers.
