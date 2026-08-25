# Design: Durable Job persistence

## Context

See `proposal.md` for motivation and `specs/durable-job-persistence/spec.md` for normative behavior.

The current persistence foundation has `MarketingRun` for one multi-step workflow's progress and `MarketingArtifact` for named durable outputs. `MarketingWorkflowPersistenceService` adds/updates/flushes without committing so a caller can atomically advance a run and store an artifact. No current component creates or executes Jobs. The Marketing Orchestrator and implemented Quality Gates foundation remain internal and `PLANNING_ONLY`; Module Registry `1.0.0` has 15 metadata-only descriptors and zero bindings.

PostgreSQL is the durable source of truth. Redis is absent and remains future transport/coordination only. Current public flows use `TaskPipelineService`, current routers/Telegram handlers, and their existing transaction behavior; this design does not connect Job persistence to any of them.

The authoritative implementation base is `bcdbd509450dd9d391ef7eeebf34134887264838`. Alembic has one head, `20260814_0003`, which created `marketing_runs` and `marketing_artifacts`.

## Goals / Non-Goals

**Goals:**

- Define one exact additive PostgreSQL Job contract and closed lifecycle.
- Keep Job, MarketingRun, and MarketingArtifact responsibilities non-overlapping.
- Preserve owner provenance by deleting aggregate-child Jobs with their owner instead of reclassifying them.
- Permit later application/workflow code to create or transition a Job atomically with related workflow-state changes.
- Make supported-boundary immutability, JSON/error safety, clocks, validation precedence, locking, and transaction ownership exact.
- Make every schema, lifecycle, migration, compatibility, isolation, and evidence obligation independently testable.

**Non-Goals:**

- No Redis/queue dependency, publication, worker claim/execution, polling, scheduler, module invocation, delivery, or workflow-engine integration.
- No retry/backoff/dead-letter policy, attempts, leases, heartbeats, worker identity, idempotency key/deduplication, per-user ordering, concurrency limits, cancellation, or timeout enforcement.
- No outbox, API/Telegram surface, LLM/OpenAI/QC call, new public DTO, or change to current synchronous behavior.
- No public or user-facing anonymous Job creation and no direct-user/system listing API.
- No database trigger, universal ORM immutability framework, generic repository abstraction, or refactor of existing persistence services.

## Decisions

### 1. Job owns a work request, not workflow progress or output

A Job represents one durable request for future asynchronous work. It owns request identity/input through the supported persistence boundary plus its own execution lifecycle. It does not own a workflow plan, current workflow state, or reusable business output:

| Aggregate | Responsibility |
| --- | --- |
| `MarketingRun` | Multi-step workflow identity, current step, workflow state, and workflow-level failure/progress |
| `MarketingArtifact` | Named structured output consumable by workflow steps |
| `Job` | One requested execution unit, its input, state, result/error, and lifecycle times |

The same data is not copied between these aggregates merely for convenience. A Job payload may contain references/inputs needed by later execution, but it does not replace `MarketingRun.state_json`; a successful Job result does not replace a durable `MarketingArtifact`. A future workflow unit may atomically transition the Job and separately upsert the artifact/run state in one caller transaction.

Ownership uses this exact truth table:

| `marketing_run_id` | `user_id` | Meaning |
| --- | --- | --- |
| non-null | null | MarketingRun-owned aggregate child |
| null | non-null | direct-user-owned aggregate child |
| null | null | trusted internal system Job |
| non-null | non-null | invalid |

“Anonymous Job” is not a separate ownership class. Public and user-facing anonymous creation is unsupported. A non-null `workflow_step` is allowed only for a run-owned Job; direct-user and system Jobs require it to be null. A run-owned Job does not duplicate the run's optional user reference because the MarketingRun is its sole aggregate owner.

Creation authorization belongs above this low-level persistence boundary:

- a future reviewed workflow application service may create a run-owned Job after authorizing access to the MarketingRun;
- trusted internal application code may create a direct-user Job after authenticating/authorizing that user;
- only an explicitly reviewed trusted internal producer may intentionally omit both owners and create a system Job;
- routers, Telegram handlers, public DTOs, and arbitrary user input never receive a switch that creates a system Job.

The persistence service validates owner shape and existence but has no request principal and does not make authorization decisions. Every future caller must own that authorization before calling it. Direct-user and system listing is deliberately absent: the creator retains the returned `job_id` and may use internal `get_job`; any user/system query surface requires a separate reviewed change.

Jobs are operational durable records, not retained audit history. Deleting a MarketingRun deletes its run-owned Jobs; deleting a User deletes its direct-user Jobs; system Jobs have no aggregate owner and survive independently. No deletion changes an owner reference to null or reclassifies a Job.

**Alternatives rejected:** `ON DELETE SET NULL` loses provenance and converts deleted-user work into system work; generic `owner_type/owner_id` loses referential integrity; simultaneous run/user ownership permits drift; retaining Jobs as an audit log requires a different retention and deletion capability.

### 2. Exact `jobs` table and ORM relationship contract

The table name is `jobs`. `JobStatus` is a Python `str, Enum` with exactly `pending`, `running`, `succeeded`, and `failed`. SQLAlchemy persists its string values in `VARCHAR(32)`, not a PostgreSQL enum.

| Column | SQL / Python type | Null | Application behavior/default | Server default | Supported-service mutability |
| --- | --- | ---: | --- | --- | --- |
| `job_id` | `VARCHAR(32)` / exact `str` | no | callable `uuid.uuid4().hex`; valid caller value allowed | none | immutable after creation |
| `user_id` | `INTEGER` / exact `int | None` | yes | `None` | none | immutable after creation |
| `marketing_run_id` | `VARCHAR(64)` / exact `str | None` | yes | `None` | none | immutable after creation |
| `workflow_step` | `VARCHAR(64)` / exact `str | None` | yes | `None` | none | immutable after creation |
| `kind` | `VARCHAR(64)` / exact `str` | no | required | none | immutable after creation |
| `status` | `VARCHAR(32)` / exact `JobStatus` | no | `pending` | `'pending'` | legal transition only |
| `payload_json` | `JSONB` / exact `dict[str, JsonValue]` | no | callable `default=dict` | `'{}'::jsonb` | immutable after creation |
| `result_json` | `JSONB` / exact `dict[str, JsonValue] | None` | yes | `None` | none | written once on success |
| `error` | `VARCHAR(4000)` / exact `str | None` | yes | `None` | none | written once on failure |
| `created_at` | `TIMESTAMPTZ` / exact aware `datetime` | no | service assigns creation instant | `now()` | immutable after creation |
| `updated_at` | `TIMESTAMPTZ` / exact aware `datetime` | no | service assigns creation/transition instant | `now()` | every legal transition |
| `started_at` | `TIMESTAMPTZ` / exact aware `datetime | None` | yes | `None` | none | set on start |
| `completed_at` | `TIMESTAMPTZ` / exact aware `datetime | None` | yes | `None` | none | set on terminal transition |

`job_id` matches `^[0-9a-f]{32}$`. It follows the repository's UUID-hex generation convention but deliberately narrows storage to the exact generated representation instead of the older permissive `VARCHAR(64)` identifier convention. No trimming, case folding, or normalization occurs. A duplicate is a primary-key violation and does not mean idempotent success.

`kind` and non-null `workflow_step` match `^[a-z][a-z0-9_.-]{0,63}$`. The vocabulary is case-sensitive and open; executable work-kind registration/binding remains future work. A run identifier is an exact built-in valid-Unicode string of 1-64 characters, excludes U+0000, and has no trimming/normalization, matching the existing permissive `MarketingRun.run_id` contract. A user identifier is an exact positive built-in integer; booleans are invalid.

Foreign keys are exact:

- `user_id -> users.id ON DELETE CASCADE`;
- `marketing_run_id -> marketing_runs.run_id ON DELETE CASCADE`.

Both `User.jobs` and `MarketingRun.jobs` use `back_populates`, `cascade="all, delete-orphan"`, and `passive_deletes=True`. The database foreign key is the authoritative unloaded-collection cascade. For a loaded collection, SQLAlchemy may issue child deletes because of the ORM delete cascade; for an unloaded collection it relies on PostgreSQL. Neither path issues owner-nullifying updates, and both paths end with the same Job rows deleted. Removing a child from either loaded aggregate collection also deletes it rather than converting it to system ownership. Tests cover loaded and unloaded parent deletion independently.

There is no `MutableDict` wrapper. `default=dict` produces a distinct empty object for every Job. The accepted input is defensively deep-copied before the first database await, so later mutation of the caller's source object cannot change the Job.

### 3. Supported-boundary immutability

`job_id`, owner references, `workflow_step`, `kind`, `payload_json`, and `created_at` are immutable **through `JobPersistenceService` after creation**. The service exposes no general update method. `transition_job` changes only `status`, `result_json`, `error`, `updated_at`, `started_at`, and `completed_at` as the legal edge requires.

The boundary handles mutation cases exactly:

- scalar reassignment and complete payload reassignment on a returned ORM object are unsupported direct-session mutation;
- top-level and nested in-place payload mutation are unsupported and are not made trackable with `MutableDict`;
- caller mutation of the original dictionary after `create_job` cannot affect the Job because validation/deep-copy completes before owner lookup or any other await;
- before a supported transition, the lock query runs with autoflush disabled and `populate_existing` enabled, reloading the row from PostgreSQL and discarding unsupported in-session mutations of immutable fields;
- the transition then mutates only lifecycle fields and performs its one explicit flush.

Tests prove each mutation form cannot be persisted *through a supported service operation*. Direct assignment followed by a caller-controlled `session.flush()` or direct SQL is explicitly outside the repository contract and may persist; this foundation does not claim universal ORM/database immutability. Tests document that unsupported behavior so callers do not rely on accidental JSON tracking semantics.

### 4. Exact JSON domain, serialization, and data safety

`payload_json` and non-null `result_json` have this exact recursive domain:

- the top level and every object are exact built-in `dict` instances;
- every key is an exact built-in `str` containing valid Unicode scalar values;
- arrays are exact built-in `list` instances;
- scalars are exactly `None`, `bool`, `int`, finite `float`, or `str`—subclasses are rejected;
- integers are bounded to signed 64-bit range `[-9223372036854775808, 9223372036854775807]`;
- strings must encode with strict UTF-8, so lone surrogates are rejected, and U+0000 is rejected because PostgreSQL `jsonb`/text cannot store it;
- tuples, sets, bytes, mappings/sequences of custom types, custom objects, NaN, and infinities are rejected;
- cycles are rejected using the active recursion path; repeated acyclic references are allowed and serialize by value;
- container depth is at most 16, counting the top-level object as depth 1 and incrementing once for each nested list or dictionary.

After structural validation, size is measured with exactly:

```python
json.dumps(
    value,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8", errors="strict")
```

The payload limit is 262,144 bytes (256 KiB). The result limit is 1,048,576 bytes (1 MiB). Equality with the limit is accepted; one byte over is rejected. `payload_json=None` maps to a new empty dictionary before validation. Empty payload and result objects are valid.

Malformed domain/Unicode/cycle/depth/serialization input raises `InvalidJobJsonError`, a subtype of `InvalidJobDataError`. A size violation raises `JobJsonTooLargeError`, also a subtype of `InvalidJobDataError`. Stable error messages name the field and category but never include raw JSON values. Validation and defensive copy complete before session access.

The service limits structured persistence; PostgreSQL only reinforces the top-level JSON-object shape. Producers must exclude credentials, tokens, secrets, raw prompts, unnecessary PII, binary media, and raw provider responses. The persistence service does not attempt unreliable automatic secret/PII detection. Media remains in image/file storage and JSON contains references/metadata only.

### 5. Persisted error safety

`transition_job` accepts only a caller-supplied sanitized exact built-in string for a failed transition. It never accepts an exception object, invokes `str(exception)`, captures a traceback, or copies a raw provider response. The caller owns redaction and must exclude credentials, tokens, secrets, raw prompts, sensitive payloads, and unnecessary PII.

The string contains valid Unicode scalar values other than U+0000, is 1-4000 characters, is not trimmed or normalized, and is stored byte-for-byte as supplied after validation. “Whitespace-only” uses the exact ASCII set U+0009 through U+000D plus U+0020. Python applies `error.strip("\t\n\v\f\r ") != ""`; PostgreSQL applies the matching predicate shown below. Other Unicode whitespace is not part of this predicate and is preserved. Oversize, invalid/unsupported Unicode, non-string, and ASCII-whitespace-only input raises `InvalidJobDataError`; no truncation or automatic stringification occurs.

### 6. Exact named database constraints

The migration and model use the following exact predicates. Python validation owns richer type/size/security rules; PostgreSQL owns relational and persisted-state coherence.

| Name | Owning fields | Exact PostgreSQL predicate | Matching Python/service evidence |
| --- | --- | --- | --- |
| `ck_jobs_job_id_format` | `job_id` | `job_id ~ '^[0-9a-f]{32}$'` | exact-string regex before query/add |
| `ck_jobs_kind_format` | `kind` | `kind ~ '^[a-z][a-z0-9_.-]{0,63}$'` | exact-string regex before add |
| `ck_jobs_workflow_step_format` | `workflow_step` | `workflow_step IS NULL OR workflow_step ~ '^[a-z][a-z0-9_.-]{0,63}$'` | nullable exact-string regex |
| `ck_jobs_exclusive_owner` | `marketing_run_id`, `user_id` | `marketing_run_id IS NULL OR user_id IS NULL` | exact ownership truth table |
| `ck_jobs_step_requires_run` | `workflow_step`, `marketing_run_id` | `workflow_step IS NULL OR marketing_run_id IS NOT NULL` | owner/step coherence validation |
| `ck_jobs_status` | `status` | `status IN ('pending', 'running', 'succeeded', 'failed')` | exact `JobStatus` validation |
| `ck_jobs_payload_object` | `payload_json` | `jsonb_typeof(payload_json) = 'object'` | exact recursive JSON validation |
| `ck_jobs_result_object` | `result_json` | `result_json IS NULL OR jsonb_typeof(result_json) = 'object'` | exact recursive JSON validation |
| `ck_jobs_lifecycle` | status/outcome/lifecycle fields | predicate below | final-coherence validation before flush |
| `ck_jobs_timestamp_order` | status/all timestamps | predicate below | one injected UTC instant per mutation |

`ck_jobs_lifecycle` is exactly SQL-equivalent to:

```sql
(
    status = 'pending'
    AND started_at IS NULL
    AND completed_at IS NULL
    AND result_json IS NULL
    AND error IS NULL
)
OR (
    status = 'running'
    AND started_at IS NOT NULL
    AND completed_at IS NULL
    AND result_json IS NULL
    AND error IS NULL
)
OR (
    status = 'succeeded'
    AND started_at IS NOT NULL
    AND completed_at IS NOT NULL
    AND result_json IS NOT NULL
    AND error IS NULL
)
OR (
    status = 'failed'
    AND started_at IS NOT NULL
    AND completed_at IS NOT NULL
    AND result_json IS NULL
    AND error IS NOT NULL
    AND btrim(error, E'\x09\x0A\x0B\x0C\x0D\x20') <> ''
)
```

`ck_jobs_timestamp_order` is exactly:

```sql
updated_at >= created_at
AND (started_at IS NULL OR started_at >= created_at)
AND (
    completed_at IS NULL
    OR (
        started_at IS NOT NULL
        AND completed_at >= started_at
    )
)
AND (
    (status = 'pending' AND updated_at = created_at)
    OR (status = 'running' AND updated_at = started_at)
    OR (status IN ('succeeded', 'failed') AND updated_at = completed_at)
)
```

Every constraint has a separate model/migration assertion and a PostgreSQL acceptance/rejection test. Names are well below PostgreSQL's 63-byte identifier limit.

### 7. Closed lifecycle and deterministic time

The exact graph is:

```text
pending -> running -> succeeded
                   \-> failed
```

| Status | Legal predecessor | Legal successor | Required | Prohibited | Timestamp equalities |
| --- | --- | --- | --- | --- | --- |
| `pending` | creation only | `running` | payload, created/updated | started/completed/result/error | `updated_at = created_at` |
| `running` | `pending` | `succeeded`, `failed` | payload, started, created/updated | completed/result/error | `updated_at = started_at >= created_at` |
| `succeeded` | `running` | none | payload, started/completed, result | error | `updated_at = completed_at >= started_at >= created_at` |
| `failed` | `running` | none | payload, started/completed, sanitized error | result | `updated_at = completed_at >= started_at >= created_at` |

Same-state, skipped, backward, and terminal transitions are illegal. Failure is terminal and representable without retries. There is no `cancelled`, `retrying`, `scheduled`, `timed_out`, `dead_lettered`, or delivery state.

`JobPersistenceService` receives an injected callable UTC clock; production defaults to an exact aware `datetime.now(timezone.utc)` provider. The service requires the returned value to be an exact aware `datetime`, normalizes it to UTC while preserving microseconds, and calls it exactly once per successful creation or legal transition.

Creation has no caller-supplied timestamp. After validation and owner existence checks, one clock value is assigned to both `created_at` and `updated_at`. No second wall-clock comparison occurs. On `pending -> running`, one post-lock instant is assigned to both `started_at` and `updated_at`. On either terminal edge, one post-lock instant is assigned to both `completed_at` and `updated_at`. A transition instant before `created_at` or, for terminal transitions, before `started_at` is rejected without mutation/flush.

Direct database inserts outside the supported service are unsupported application behavior. Both timestamp columns nevertheless use `server_default=now()`; PostgreSQL transaction time gives them the same initial value. The server default is creation fallback only and never updates `updated_at` automatically.

### 8. Exact internal persistence service

Future runtime ownership is `app/services/job_persistence_service.py`. The service is instantiated with an optional injected clock and exposes only:

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
) -> Job
```

No method accepts `created_at`, `occurred_at`, an exception object, a user/system list filter, pagination, or a generic field update.

The exact error taxonomy is:

- `JobPersistenceError`: stable safe base domain error;
- `InvalidJobDataError`: invalid identifier/key/owner/error/clock input;
- `InvalidJobJsonError(InvalidJobDataError)`: invalid JSON type, cycle, depth, Unicode, integer, finite-number, or serialization input;
- `JobJsonTooLargeError(InvalidJobDataError)`: payload/result canonical UTF-8 size exceeded;
- `JobNotFoundError`: a valid transition target is absent;
- `IllegalJobTransitionError`: the locked current state cannot legally precede the requested target or target/outcome combination is illegal.

Messages never include raw payload, result, error, credential, or provider values. Duplicate primary-key, foreign-key race, check-constraint, and other SQLAlchemy/database failures are not translated; the “database error translation” step is explicitly pass-through so the original exception reaches the caller for rollback.

#### `create_job` total order

1. Validate exact input types and identifier/key formats without session access.
2. Validate the ownership truth table and workflow-step coherence.
3. Validate/canonical-measure/deep-copy payload JSON before any await.
4. With autoflush disabled, query the specified User or MarketingRun by primary key; missing owner raises `InvalidJobDataError`. System ownership performs no owner query. This existence check is not authorization and the foreign key remains authoritative against races.
5. Call the injected clock once and validate/normalize it.
6. Construct exact `pending` state with `created_at = updated_at` and no lifecycle outcome fields.
7. Add the Job.
8. Flush exactly once.
9. Pass any database exception through unchanged; do not roll back.
10. Return the Job without refresh.

Input validation therefore wins over missing-owner/database errors. A pending owner not yet flushed by its own service is not considered existing; callers creating a run and Job atomically call the existing run service first, whose create operation flushes without committing.

#### `get_job` total order

1. Validate exact Job-ID syntax; malformed input raises `InvalidJobDataError` before session access.
2. Query by primary key with autoflush disabled and no lock.
3. Return the Job or `None` for a valid missing ID.

It does not flush, refresh, commit, or roll back.

#### `list_jobs_for_run` total order

1. Validate an exact 1-64 character run ID with no trimming/normalization.
2. Query with autoflush disabled, no lock, and `ORDER BY created_at ASC, job_id ASC`.
3. Return all matching rows; a valid nonexistent run returns an empty list.

There is intentionally no run existence pre-query, limit, pagination, refresh, direct-user listing, or system listing. Any bounded/public query surface requires a later reviewed change.

#### `transition_job` total order

1. Validate Job-ID syntax.
2. Require an exact `JobStatus` target value; raw strings/aliases are invalid.
3. Validate target/outcome presence rules and any supplied result/error type, JSON, canonical size, Unicode, and sanitization properties before session access. Pure input errors take precedence over missing Job/state errors.
4. With autoflush disabled, select the exact Job row by primary key using `FOR UPDATE` and `populate_existing`, discarding unsupported in-session immutable-field changes.
5. Raise `JobNotFoundError` if the valid target is absent.
6. Evaluate the locked current state and raise `IllegalJobTransitionError` for a same-state, skipped, backward, terminal, or otherwise illegal edge before clock access or mutation.
7. Call the injected clock once; validate/normalize it and validate ordering against the locked row.
8. Apply only the target status, allowed outcome, and exact lifecycle timestamp fields.
9. Validate the complete final lifecycle/timestamp coherence in memory.
10. Flush exactly once.
11. Pass any database exception through unchanged; do not roll back.
12. Return the Job without refresh.

For multiple invalid conditions, precedence is: malformed pure input -> valid-target not found -> illegal locked transition -> invalid clock/order -> database failure. No failed operation mutates or explicitly flushes a lifecycle update.

### 9. Transaction and concurrency boundary

The rule remains:

```text
service may add/flush
service never commits
service never rolls back
caller owns transaction and rollback
```

A future caller can use one `AsyncSession` transaction for Job creation/transition plus MarketingRun/MarketingArtifact mutations. Flush establishes database validity but not durability. PostgreSQL commit is the durability boundary. If any flush or later operation fails, the exception propagates and the caller rolls back the entire unit.

The row lock serializes transitions only. It is held until caller commit/rollback. A waiting transaction evaluates the newly committed state after lock acquisition and applies only a still-legal transition. A missing row acquires no row lock. Lock timeout/deadlock policy remains later caller/worker infrastructure work; this is not a claim, lease, distributed lock, retry, or recovery mechanism.

A committed `pending` Job is durable but inert. This design provides no atomicity with future Redis publication, delivery guarantee, outbox, or execution guarantee.

### 10. Exact index and migration contract

The final indexes are:

- the primary-key index on `job_id`, used by `get_job` and transition lookup;
- `ix_jobs_run_created_job` on `(marketing_run_id ASC, created_at ASC, job_id ASC)`, used by `list_jobs_for_run`;
- `ix_jobs_status_created_job` on `(status ASC, created_at ASC, job_id ASC)`, schema preparation for a separately reviewed future bounded status/worker scan only.

There is no user index and no kind index because this foundation supports neither query. Nullable run ownership does not prevent the run-equality query from using its composite index. Any direct-user/system/kind query or different recovery ordering requires a separate reviewed change.

Plan one new Alembic revision, proposed ID `20260825_0004`, with exact parent `20260814_0003`. The apply step must re-check the sole current head before generation.

Upgrade operations, in order:

1. create `jobs` with exactly the approved columns, primary key, two `ON DELETE CASCADE` foreign keys, server defaults, and ten named checks;
2. create `ix_jobs_run_created_job`;
3. create `ix_jobs_status_created_job`.

Downgrade drops `ix_jobs_status_created_job`, then `ix_jobs_run_created_job`, then `jobs`. It does not modify existing tables, constraints, indexes, or historical rows. Upgrade, downgrade, re-upgrade, reflected schema, static operations, and single-head continuity each receive separate evidence. PostgreSQL tests use an isolated/serial migration fixture and restore the expected revision even on failure.

### 11. Compatibility, isolation, and evidence ownership

The later implementation leaves unchanged:

- `/chat`, `/tasks`, `/images`, `/brand-profile`, deprecated `/agents`, presenters, public DTOs, and Telegram handlers;
- `TaskPipelineService`, `TaskRouter`, `AgentRunner`, `AgentRegistry`, agents, and existing call counts;
- `MarketingWorkflowPersistenceService`, MarketingRun status semantics, and MarketingArtifact upsert/uniqueness/cascade/list order;
- Marketing Orchestrator planner/validator behavior and `PLANNING_ONLY` readiness;
- implemented Quality Gates contracts, fingerprints, decisions, isolation, and `PLANNING_ONLY` readiness;
- Module Registry `1.0.0`, 15 descriptors, zero bindings, and checksum `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`;
- dependency manifests, Docker/Compose/CI, environment variables, package resources, and LLM/OpenAI/QC call counts.

Independent isolation evidence covers Redis; worker/queue behavior; LLM/OpenAI; `QCService`; `TaskPipelineService`; autonomous persistence commit/rollback; API/Telegram; and other URL/image/external calls. No current runtime path imports or calls Job persistence.

Future implementation is expected to touch only `app/models.py`, `app/services/job_persistence_service.py`, one new migration from the rechecked head, focused tests, this change's task state, and its verification document. This reconciliation itself changes planning/documentation only.

## Risks / Trade-offs

- [Owner deletion removes Job history] -> Jobs are explicitly operational aggregate records, not an audit log; no deletion reclassifies them.
- [Trusted code misuses system ownership] -> no public switch exists; every future producer requires reviewed authorization/wiring.
- [Direct session writes bypass supported immutability/limits] -> document them as unsupported, reload before supported transitions, and avoid claiming universal enforcement.
- [Bounded JSON rejects future large real outputs] -> store references/artifacts instead; changing limits requires evidence and a reviewed contract update.
- [Sanitized errors omit debugging detail] -> diagnostics belong in secured observability, not durable user/work records.
- [A committed pending Job is mistaken for enqueued work] -> describe it as durable-but-inert until queue integration.
- [Status index is mistaken for polling design] -> identify it as schema preparation only; no scan/claim method exists.
- [Row locks can wait/deadlock] -> keep caller-owned transactions short; worker timeout/retry policy remains out of scope.

## Migration Plan

1. Re-check the clean branch, single Alembic head, and accepted artifacts.
2. Add the exact model/status/relationships and separately test every constraint/default/immutability rule.
3. Generate one migration from the then-current sole head and reconcile it to the exact two-FK/two-index/ten-check contract.
4. Add the persistence service, injected clock, validators, lifecycle, transaction, and concurrency evidence without wiring a caller.
5. Verify isolated PostgreSQL upgrade, downgrade, re-upgrade, head continuity, compatibility/isolation, full tests, compilation, and strict OpenSpec validation.
6. Deploy the additive migration before any later trusted producer is authorized to create Jobs.

Rollback before dependent changes is a one-revision Alembic downgrade followed by code revert. Later dependent migrations or live Job rows require a separately reviewed rollback/retention plan; this foundation does not silently downgrade production data.

There are no intentionally deferred questions that would change the schema, service behavior, or task breakdown.
