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

## Supported-boundary immutability

Identity, owners, workflow step, kind, payload, and creation time are immutable through supported Job persistence operations after creation. Input dictionaries are validated and deep-copied before database access, and each empty payload uses a distinct callable default.

Direct ORM/session assignment or in-place JSON mutation followed by a caller-controlled flush is unsupported and is not claimed to be universally prevented. The foundation introduces no `MutableDict`, database trigger, or repository-wide immutability framework. A supported transition reloads the locked PostgreSQL row without autoflush and writes only lifecycle fields.

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

- `pending`: `updated_at = created_at`; no result, error, start, or completion time.
- `running`: `updated_at = started_at >= created_at`; no result, error, or completion time.
- `succeeded`: terminal; structured result and `updated_at = completed_at >= started_at` are required; error is prohibited.
- `failed`: terminal; sanitized error and `updated_at = completed_at >= started_at` are required; result is prohibited.

One injected aware UTC clock is called once per creation/legal transition. Same-state, skipped, backward, and terminal transitions are illegal. Retry, cancellation, timeout, dead-letter, delivery, and worker-lease states are not part of this vocabulary.

## Persistence and transaction boundary

The planned internal service creates, validates lookup identifiers, lists run Jobs deterministically, and performs row-locked legal transitions using exact validation precedence. Mutations add/flush once and never refresh, commit, or roll back. The caller owns rollback and may atomically combine Job, MarketingRun, and MarketingArtifact changes.

PostgreSQL commit is the durability boundary. A committed Job is not proof that work was published, claimed, or executed. Cross-system publication/recovery and semantic deduplication require later queue/reliability changes; this foundation introduces no outbox.

The only secondary indexes are run/created/job for run listing and status/created/job as schema preparation for a separately reviewed future bounded scan. There is no user or kind index.

## Compatibility and non-goals

The foundation must not change existing API/Telegram contracts, standalone task execution, MarketingRun/MarketingArtifact behavior, Marketing Orchestrator planning, implemented planning-only Quality Gates, Module Registry metadata, agents/presenters, dependencies, or LLM/QC call counts.

It introduces no Redis, queue framework, worker, scheduler, polling, delivery, module execution, retry/backoff, idempotency, ordering, concurrency limit, cancellation, timeout, API endpoint, Telegram UX, or OpenAI/QC call.

The exact schema, predicates, service algorithms, migration parent, security limits, and independently checkable evidence tasks are normative in `openspec/changes/add-durable-job-persistence/`.
