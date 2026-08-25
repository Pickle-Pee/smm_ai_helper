## Purpose

Define secure, bounded PostgreSQL-backed records for individual future asynchronous work requests, including exact ownership, lifecycle, and transaction-safe persistence behavior without queue or execution integration.

## ADDED Requirements

### Requirement: Persist one durable unit of future work

The system SHALL persist each Job as one durable execution request with a stable lowercase 32-character UUID-hex identifier, non-empty kind, bounded structured input payload, closed lifecycle state, and timezone-aware timestamps. A Job SHALL remain distinct from MarketingRun workflow progress and MarketingArtifact output.

#### Scenario: Create a Job

- **GIVEN** valid input and an authorized ownership association
- **WHEN** a Job is created through the supported persistence boundary
- **THEN** it SHALL begin in `pending`
- **AND** SHALL have one creation instant assigned to both creation and update timestamps
- **AND** SHALL have no start time, completion time, result, or error

#### Scenario: Durable after commit

- **GIVEN** valid Job creation participating in a caller-owned database transaction
- **WHEN** the caller commits that transaction
- **THEN** the Job SHALL remain loadable after the creating process ends
- **AND** PostgreSQL SHALL be the canonical record of its state

### Requirement: Preserve exact ownership provenance

A Job SHALL be exactly one MarketingRun-owned aggregate child, one direct-user-owned aggregate child, or a trusted internal system Job with neither owner reference. Both owner references SHALL NOT be non-null together. “Anonymous Job” SHALL NOT be a separate ownership class, and public or user-facing anonymous/system creation SHALL NOT be supported. A workflow step SHALL be allowed only for a run-owned Job.

#### Scenario: Create run-owned Job

- **GIVEN** an existing MarketingRun and an authorized internal workflow caller
- **WHEN** the caller creates a Job for that run and optional workflow step
- **THEN** the Job SHALL reference the MarketingRun
- **AND** SHALL NOT store a direct user owner

#### Scenario: Create direct-user Job

- **GIVEN** an existing user and trusted application code that has authorized that user
- **WHEN** the caller creates a runless Job for the user
- **THEN** the Job SHALL reference only that user
- **AND** SHALL NOT declare a workflow step

#### Scenario: Create system Job

- **GIVEN** an explicitly reviewed trusted internal producer
- **WHEN** it intentionally creates a Job with both owner references absent
- **THEN** the Job SHALL be classified as system work
- **AND** no public API, Telegram input, or anonymous-user switch SHALL be involved

#### Scenario: Reject invalid owner combination

- **WHEN** creation declares both a MarketingRun and user, or a workflow step without a MarketingRun
- **THEN** validation SHALL reject the request before adding or flushing a Job

### Requirement: Delete Jobs with their aggregate owner

Run-owned and direct-user-owned Jobs SHALL be operational aggregate records rather than retained audit history. Deleting a MarketingRun SHALL delete its run-owned Jobs, and deleting a User SHALL delete its direct-user Jobs. Owner deletion SHALL NOT null an owner reference or reclassify a Job as system work. Loaded and unloaded ORM collections SHALL produce the same final database result without owner-nullifying updates.

#### Scenario: Delete MarketingRun

- **GIVEN** a MarketingRun with owned Jobs and MarketingArtifacts
- **WHEN** the MarketingRun is deleted
- **THEN** its Jobs SHALL be deleted through ORM/database cascade behavior
- **AND** existing MarketingArtifact cascade behavior SHALL remain unchanged

#### Scenario: Delete direct user

- **GIVEN** a user with direct-user-owned Jobs
- **WHEN** the user is deleted
- **THEN** those Jobs SHALL be deleted
- **AND** none SHALL survive as a system Job

#### Scenario: Delete owner with unloaded collection

- **GIVEN** an aggregate owner whose Jobs collection is not loaded
- **WHEN** the owner is deleted
- **THEN** PostgreSQL `ON DELETE CASCADE` SHALL delete the Jobs
- **AND** the final rows SHALL match deletion with a loaded collection

### Requirement: Keep request identity and input immutable through the supported boundary

After creation, the supported persistence operations SHALL expose no way to change Job identity, owner references, workflow step, kind, payload, or creation time. Lifecycle transition SHALL reload the locked persisted row before mutation and SHALL update only status, outcome, and lifecycle timestamps. Direct SQLAlchemy/session mutation outside the persistence boundary SHALL be unsupported and SHALL NOT be described as universally prevented.

#### Scenario: Caller mutates original payload

- **GIVEN** a caller-supplied payload accepted during Job creation
- **WHEN** the caller mutates its original dictionary after the creation call
- **THEN** the Job payload SHALL remain the defensively copied accepted value

#### Scenario: Unsupported returned-object mutation precedes transition

- **GIVEN** a caller directly reassigns or mutates immutable fields on a returned ORM Job
- **WHEN** a supported lifecycle transition subsequently locks that Job
- **THEN** the transition SHALL reload the persisted immutable fields without autoflush
- **AND** SHALL persist only the legal lifecycle mutation

#### Scenario: Direct session mutation remains unsupported

- **WHEN** a caller bypasses the persistence boundary and directly flushes reassigned or in-place-mutated Job fields
- **THEN** the foundation SHALL make no universal immutability guarantee for that unsupported behavior
- **AND** SHALL NOT introduce `MutableDict`, a database trigger, or a repository-wide ORM immutability framework

### Requirement: Accept only the exact bounded JSON domain

Payload and non-null result SHALL be exact top-level dictionaries. Recursively, objects SHALL be exact dictionaries with exact string keys, arrays SHALL be exact lists, and scalar values SHALL be exactly null, boolean, signed 64-bit integer, finite float, or valid-Unicode string. Cycles, depth greater than 16 containers, lone surrogates, U+0000, non-string keys, non-finite numbers, unsupported containers, bytes, subclasses, and custom objects SHALL be rejected before session access.

Canonical measurement SHALL use UTF-8 encoding of JSON serialized with `ensure_ascii=False`, sorted keys, compact separators, and non-finite values disabled. Payload SHALL be at most 262,144 bytes and result SHALL be at most 1,048,576 bytes; equality SHALL be accepted and one byte over SHALL raise a typed size error. Producers SHALL exclude secrets, credentials, raw prompts, raw provider responses, binary media, and unnecessary PII; the persistence boundary SHALL NOT attempt automatic secret detection.

#### Scenario: Accept bounded nested JSON

- **WHEN** payload or result is an acyclic exact dictionary within the type, depth, integer, Unicode, and canonical byte limits
- **THEN** validation SHALL accept and defensively deep-copy it

#### Scenario: Reject unsupported JSON type

- **WHEN** payload or result contains a non-string key, unsupported/custom container, bytes, custom object, subclass value, or non-finite float
- **THEN** validation SHALL raise a typed JSON error before session access

#### Scenario: Reject cyclic or excessive-depth JSON

- **WHEN** payload or result contains a reference cycle or a container at depth 17
- **THEN** validation SHALL raise a typed JSON error before serialization or session access

#### Scenario: Reject invalid or PostgreSQL-unsupported Unicode JSON

- **WHEN** a key or string value contains a lone Unicode surrogate or U+0000
- **THEN** strict UTF-8 validation SHALL raise a typed JSON error

#### Scenario: Reject oversize JSON

- **WHEN** canonical UTF-8 payload or result size exceeds its field limit by at least one byte
- **THEN** validation SHALL raise a typed size error before session access

### Requirement: Persist only caller-sanitized failure errors

A failed transition SHALL accept only a caller-supplied exact built-in string of 1-4000 valid Unicode scalar values excluding U+0000. The value SHALL be stored without trimming or normalization but SHALL contain a non-whitespace character after removing only ASCII U+0009 through U+000D and U+0020 from both ends. The persistence boundary SHALL NOT accept an exception object, automatically stringify exceptions, persist tracebacks, or copy raw provider responses. The caller SHALL redact secrets, tokens, credentials, raw prompts, sensitive payloads, and unnecessary PII.

#### Scenario: Persist approved sanitized error

- **GIVEN** a caller-supplied sanitized error satisfying the exact type, length, Unicode, and whitespace rule
- **WHEN** a running Job transitions to `failed`
- **THEN** the exact supplied string SHALL be persisted unchanged

#### Scenario: Reject whitespace-only error

- **WHEN** a failed transition supplies an empty string or only the defined ASCII whitespace set
- **THEN** validation and database lifecycle coherence SHALL reject it

#### Scenario: Reject oversize or non-string error

- **WHEN** a failed transition supplies more than 4000 characters or any value whose exact type is not string
- **THEN** a typed invalid-data error SHALL be raised without truncation or stringification

#### Scenario: Reject exception object

- **WHEN** a failed transition receives an exception object instead of a sanitized string
- **THEN** validation SHALL reject it
- **AND** SHALL NOT call `str()` or persist traceback/provider content automatically

### Requirement: Enforce a closed Job lifecycle

The only states SHALL be `pending`, `running`, `succeeded`, and `failed`. The only legal edges SHALL be `pending -> running`, `running -> succeeded`, and `running -> failed`. Same-state, skipped, backward, and terminal transitions SHALL be illegal, and failure SHALL be representable without retry behavior.

#### Scenario: Start pending Job

- **GIVEN** a `pending` Job
- **WHEN** it transitions to `running`
- **THEN** one transition instant SHALL be assigned to both start and update timestamps
- **AND** result, error, and completion time SHALL remain absent

#### Scenario: Complete running Job successfully

- **GIVEN** a `running` Job and a valid bounded result object
- **WHEN** it transitions to `succeeded`
- **THEN** one transition instant SHALL be assigned to both completion and update timestamps
- **AND** the copied result SHALL be persisted and error SHALL remain absent

#### Scenario: Complete running Job with failure

- **GIVEN** a `running` Job and a valid caller-sanitized error
- **WHEN** it transitions to `failed`
- **THEN** one transition instant SHALL be assigned to both completion and update timestamps
- **AND** the error SHALL be persisted and result SHALL remain absent

#### Scenario: Reject illegal transition

- **GIVEN** a Job whose locked current state cannot legally precede the requested state
- **WHEN** transition is requested
- **THEN** a typed illegal-transition error SHALL be raised
- **AND** no clock call, lifecycle mutation, or explicit flush SHALL occur

### Requirement: Use deterministic UTC lifecycle timestamps

The persistence boundary SHALL own one injected/testable UTC clock. Creation SHALL call it once after owner validation and set `created_at = updated_at`. Every legal transition SHALL call it once after row locking and legality validation. Running SHALL satisfy `updated_at = started_at >= created_at`; terminal states SHALL satisfy `updated_at = completed_at >= started_at >= created_at`. The server defaults for creation and update timestamps SHALL both be PostgreSQL `now()` for unsupported direct inserts, but a server default SHALL NOT be described as automatic update behavior.

#### Scenario: Deterministic creation clock

- **GIVEN** a deterministic aware clock value with microseconds
- **WHEN** a Job is created
- **THEN** the clock SHALL be called exactly once
- **AND** both creation and update timestamps SHALL equal its UTC-normalized value with microseconds preserved

#### Scenario: Reject naive or invalid clock

- **WHEN** the injected clock returns a naive datetime, subclass, string, or otherwise invalid instant
- **THEN** a typed invalid-data error SHALL be raised before object mutation or flush

#### Scenario: Reject backwards transition time

- **WHEN** a legal edge obtains an instant before creation, or a terminal edge obtains an instant before start
- **THEN** transition SHALL fail without mutation or explicit flush

### Requirement: Provide deterministic internal persistence operations

The internal boundary SHALL support creation, validated lookup by Job identifier, deterministic unbounded listing for one MarketingRun, and lifecycle transition. It SHALL not support direct-user/system listing, pagination, generic filtering, or generic field mutation. Creators SHALL retain returned Job identifiers; future query surfaces require a separate reviewed change.

Pure input validation SHALL precede database access. For transition, valid-target absence SHALL precede locked-state legality, which SHALL precede clock/order validation and database flush errors. Mutation methods SHALL return without refresh; read methods SHALL not flush or refresh.

#### Scenario: Load malformed Job identifier

- **WHEN** lookup receives a value outside exact lowercase 32-character UUID-hex syntax
- **THEN** it SHALL raise a typed invalid-data error before querying

#### Scenario: Load valid missing Job

- **WHEN** a syntactically valid Job identifier is not persisted
- **THEN** lookup SHALL return no Job

#### Scenario: Transition valid missing Job

- **WHEN** a lifecycle transition targets a syntactically valid unknown Job after pure inputs validate
- **THEN** it SHALL raise a typed not-found error before state/clock processing

#### Scenario: List run Jobs

- **GIVEN** a valid exact 1-64 character MarketingRun identifier containing valid Unicode scalar values other than U+0000
- **WHEN** run Jobs are listed
- **THEN** all matching rows SHALL be returned in `created_at ASC, job_id ASC` order without locking, pagination, or refresh
- **AND** a valid nonexistent run SHALL return an empty list without a run-existence query

#### Scenario: Duplicate Job identifier

- **GIVEN** a persisted Job identifier
- **WHEN** another Job is flushed with that identifier
- **THEN** the database exception SHALL propagate unchanged
- **AND** no second Job row SHALL be committed

### Requirement: Preserve caller-owned transactions and serialize transitions

Job mutations SHALL add or flush within the supplied session and SHALL NOT commit, roll back, or refresh independently. Lifecycle transition SHALL select exactly one Job by primary key using a row-level lock, autoflush disabled, and persisted-row reload; current state SHALL be evaluated only after the lock is acquired. Database failures SHALL propagate unchanged for caller-owned rollback.

#### Scenario: Create without autonomous transaction ownership

- **WHEN** a valid Job is created
- **THEN** the boundary SHALL add and explicitly flush once
- **AND** SHALL not commit, roll back, or refresh

#### Scenario: Atomically update Job and workflow state

- **GIVEN** a Job mutation plus MarketingRun and MarketingArtifact mutations in one caller-owned transaction
- **WHEN** all operations succeed and the caller commits
- **THEN** all PostgreSQL mutations SHALL become durable atomically

#### Scenario: Roll back partial unit of work

- **GIVEN** a Job mutation was flushed but a later operation fails
- **WHEN** the caller rolls back
- **THEN** no mutation from that transaction SHALL remain durable

#### Scenario: Concurrent transition

- **GIVEN** two transactions attempt to transition the same Job
- **WHEN** the first locks and commits a legal edge
- **THEN** the second SHALL evaluate the newly committed state after acquiring the lock
- **AND** SHALL apply only a transition that remains legal

### Requirement: Add one reversible schema revision

The capability SHALL use one additive migration from sole head `20260814_0003`. Upgrade SHALL create only `jobs`, ten named checks, two `ON DELETE CASCADE` foreign keys, and secondary indexes `ix_jobs_run_created_job` and `ix_jobs_status_created_job`. No user or kind index SHALL be added. Downgrade SHALL remove the two indexes in reverse order and then the table.

#### Scenario: Upgrade from current head

- **GIVEN** an isolated PostgreSQL database at `20260814_0003`
- **WHEN** the Job migration is applied
- **THEN** the exact table, defaults, checks, foreign keys, and two secondary indexes SHALL exist
- **AND** earlier tables and data SHALL remain unchanged

#### Scenario: Downgrade Job revision

- **GIVEN** a database with no later dependent revision
- **WHEN** it is downgraded one revision
- **THEN** only Job structures SHALL be removed
- **AND** the database SHALL return to `20260814_0003`

#### Scenario: Deterministic re-upgrade

- **GIVEN** successful downgrade to `20260814_0003`
- **WHEN** the Job revision is applied again
- **THEN** it SHALL recreate the identical reflected contract as the first upgrade

### Requirement: Remain persistence-only and backward compatible

Adding durable Job persistence SHALL NOT enqueue, claim, execute, retry, cancel, time out, deliver, or deduplicate work. It SHALL NOT alter existing API/Telegram contracts, synchronous task behavior, Marketing Orchestrator planning, implemented Quality Gates behavior, Module Registry metadata, MarketingRun/MarketingArtifact behavior, dependencies, or model/QC call counts.

#### Scenario: Persist Job before queue infrastructure exists

- **WHEN** a Job is committed before separately reviewed queue/worker integration exists
- **THEN** the Job SHALL be durable but inert in PostgreSQL
- **AND** no Redis publication, worker/queue call, polling, module execution, LLM/OpenAI call, QCService call, or delivery SHALL occur

#### Scenario: Existing runtime flow

- **WHEN** an existing chat, task, image, brand-profile, direct-agent, Orchestrator, Quality Gates, or Telegram flow runs
- **THEN** its contract and execution path SHALL remain unchanged
- **AND** it SHALL NOT require Job persistence
