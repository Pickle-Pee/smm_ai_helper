# Durable Job persistence product contract

Status: reconciled pre-implementation design; no runtime Job model, service, migration, queue, or worker exists yet.

## Responsibility and retention

A durable Job represents one future asynchronous execution request whose canonical lifecycle record belongs in PostgreSQL. It is intentionally narrower than a workflow:

- `MarketingRun` owns multi-step workflow progress and state.
- `MarketingArtifact` owns named durable workflow outputs.
- `Job` owns one request's input through the supported persistence boundary, execution status, result/error, and lifecycle timestamps.

A Job result does not replace a MarketingArtifact, and Job status does not replace MarketingRun status. Jobs are operational records, not retained audit history.

## Ownership and authorization

Ownership is exclusive:

| MarketingRun | User | Meaning | Deletion |
| --- | --- | --- | --- |
| present | absent | run-owned Job | deleted with MarketingRun |
| absent | present | direct-user-owned Job | deleted with User |
| absent | absent | system Job | survives independently |
| present | present | invalid | rejected |

“Anonymous Job” is not a separate class. Public and user-facing anonymous/system creation is unsupported. Only explicitly reviewed trusted internal application code may create system Jobs. Future workflow/direct-user producers authorize their owner before calling the low-level persistence service; that service verifies owner shape/existence but does not replace caller authorization.

A workflow step is valid only for a run-owned Job. A Job has no direct Module Registry ownership or execution binding. Direct-user/system listing is intentionally absent: an internal creator retains `job_id` and may perform lookup; future query surfaces require a separate reviewed change.

The ORM contract is bidirectional and explicit: `Job.user <-> User.jobs` and `Job.marketing_run <-> MarketingRun.jobs`. The Job-side relationships are navigation-only after creation and do not cascade deletion to an owner. The owner-side collections use aggregate-child `all, delete-orphan` cascade with passive database deletes. Removing an owned Job from either collection deletes it; it never silently becomes system-owned.

## Supported-boundary immutability

Identity, owners, workflow step, kind, payload, and creation time are immutable through supported Job persistence operations after creation. Version is service-managed and caller-read-only. Input dictionaries are validated and deep-copied before database access, and each empty payload uses a distinct callable default.

Before any transition SQL or lock, the service inspects already identity-mapped target state without autoflush. It rejects tracked changes to protected scalars or version, either Job-side owner relationship, identity-mapped owner collections involving the target, and pending target deletion with a typed dirty-mutation error that instructs the caller to roll back. Rejection performs no SQL, refresh, expiration, state restoration, lifecycle/version mutation, or explicit flush; unrelated dirty objects remain untouched and do not block the operation.

Plain JSON uses no `MutableDict`. Whole-value payload reassignment or explicitly flagged history is tracked and rejected. Ordinary in-place top-level or nested dictionary mutation is not tracked; after the dirty-state gate passes, a supported transition reloads the locked PostgreSQL row with `populate_existing`, replacing that in-memory JSON before flushing only legal lifecycle/version fields. Direct ORM/session mutation followed by a caller-controlled flush remains unsupported and is not claimed to be universally prevented. The foundation introduces no database trigger or repository-wide immutability framework.

## Bounded JSON and persisted-error safety

Payload/result values use exact dictionaries/lists and exact JSON scalar types. Integers are signed 64-bit; floats are finite; strings/keys must be strict UTF-8 Unicode scalar values excluding PostgreSQL-unsupported U+0000. Cycles, custom/subclass containers, bytes, non-string keys, invalid Unicode, unsupported values, and container depth above 16 are rejected.

Canonical compact sorted-key UTF-8 JSON is limited to:

- payload: 262,144 bytes (256 KiB);
- result: 1,048,576 bytes (1 MiB).

Producers exclude secrets, credentials, raw prompts/provider responses, binary media, and unnecessary PII. The persistence service does not attempt unreliable automatic secret detection.

A failed transition accepts only a caller-supplied sanitized exact string of 1-4000 characters. It stores the approved string unchanged, rejects the defined ASCII-whitespace-only domain, and never stringifies exception objects, captures tracebacks, truncates errors, or copies raw provider responses automatically.

## Closed lifecycle and time

```text
pending -> running -> succeeded
                   \-> failed
```

- `pending`, version `0`: `updated_at = created_at`; no result, error, start, or completion time.
- `running`, version `1`: `updated_at = started_at >= created_at`; no result, error, or completion time.
- `succeeded`, version `2`: terminal; structured result and `updated_at = completed_at >= started_at` are required; error is prohibited.
- `failed`, version `2`: terminal; sanitized error and `updated_at = completed_at >= started_at` are required; result is prohibited.

One injected aware UTC clock is called once per creation/legal transition. The schema stores `version INTEGER NOT NULL` with application/server defaults `0` and `ck_jobs_version_nonnegative`. Each successful transition increments the persisted version exactly once. After lock and stale comparison, persisted version `2147483647` raises `JobVersionExhaustedError` before lifecycle legality, clock access, mutation, flush, or any attempt to store `2147483648`. Validation, dirty, missing, stale, exhausted, illegal, and clock/order rejection does not mutate version; a database flush failure cannot make its candidate increment durable and requires caller rollback. Same-state, skipped, backward, and terminal transitions are illegal. Retry, cancellation, timeout, dead-letter, delivery, and worker-lease states are not part of this vocabulary.

## Persistence and transaction boundary

The planned internal service creates, validates lookup identifiers, lists run Jobs deterministically, and performs row-locked legal transitions using exact validation precedence. Every transition requires the caller's exact observed `expected_version`; after locking and reloading, a mismatch raises a typed stale-version error, then a matching maximum version raises the typed exhaustion error, both before lifecycle legality, clock access, mutation, or flush. Thus two commands based on the same observed version cannot both succeed, while a later command based on a newly observed committed version may succeed sequentially. The row lock remains the transaction-serialization mechanism; this design does not replace it with compare-and-swap SQL.

Mutations add/flush once and never refresh, commit, or roll back. The caller owns rollback and may atomically combine Job, MarketingRun, and MarketingArtifact changes.

PostgreSQL commit is the durability boundary. A committed Job is not proof that work was published, claimed, or executed. Cross-system publication/recovery and semantic deduplication require later queue/reliability changes; this foundation introduces no outbox.

The only secondary indexes are run/created/job for run listing and status/created/job as schema preparation for a separately reviewed future bounded scan. There is no user or kind index.

## Compatibility and non-goals

The foundation must not change existing API/Telegram contracts, standalone task execution, MarketingRun/MarketingArtifact behavior, Marketing Orchestrator planning, implemented planning-only Quality Gates, Module Registry metadata, agents/presenters, dependencies, or LLM/QC call counts.

It introduces no Redis, queue framework, worker, scheduler, polling, delivery, module execution, retry/backoff, idempotency, ordering, concurrency limit, cancellation, timeout, API endpoint, Telegram UX, or OpenAI/QC call.

The exact schema, predicates, service algorithms, migration parent, security limits, and independently checkable evidence tasks are normative in `openspec/changes/add-durable-job-persistence/`.
