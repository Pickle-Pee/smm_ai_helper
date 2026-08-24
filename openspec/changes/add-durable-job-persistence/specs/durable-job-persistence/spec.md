## Purpose

Define durable PostgreSQL-backed records for individual future asynchronous work requests, including their closed lifecycle and transaction-safe persistence boundary, without introducing queue or execution behavior.

## ADDED Requirements

### Requirement: Persist one durable unit of future work

The system SHALL persist each Job as one durable execution request with a stable identifier, a non-empty kind, a structured input payload, lifecycle state, and timestamps. A Job SHALL remain distinct from MarketingRun workflow progress and MarketingArtifact output.

#### Scenario: Create a Job

- **GIVEN** a valid kind, payload, and optional owner association
- **WHEN** a Job is created
- **THEN** it SHALL receive a stable lowercase UUID-hex identifier
- **AND** SHALL begin in `pending`
- **AND** SHALL persist its input and creation/update timestamps
- **AND** SHALL have no start time, completion time, result, or error

#### Scenario: Durable after commit

- **GIVEN** a valid Job creation participating in a caller-owned database transaction
- **WHEN** the caller commits that transaction
- **THEN** the Job SHALL remain loadable after the creating process ends
- **AND** PostgreSQL SHALL be the canonical record of its state

### Requirement: Represent explicit optional ownership

A Job SHALL be owned by at most one optional domain association: a MarketingRun, a user, or neither for system/anonymous work. A run-owned Job SHALL NOT also store a direct user owner. A Job MAY exist without a MarketingRun, and a workflow-step reference SHALL be allowed only for a run-owned Job.

#### Scenario: Run-owned Job

- **GIVEN** an existing MarketingRun
- **WHEN** a Job is created for that run and optional workflow step
- **THEN** the Job SHALL reference that run
- **AND** SHALL NOT also reference a direct user owner

#### Scenario: Runless Job

- **WHEN** a Job is created without a MarketingRun
- **THEN** it SHALL be persistable with an optional user owner or with neither owner reference
- **AND** it SHALL NOT declare a workflow step

#### Scenario: Invalid owner combination

- **WHEN** a Job declares both a MarketingRun and direct user owner, or declares a workflow step without a MarketingRun
- **THEN** persistence SHALL reject the record

### Requirement: Enforce a closed Job lifecycle

The only Job states SHALL be `pending`, `running`, `succeeded`, and `failed`. The only legal transitions SHALL be `pending -> running`, `running -> succeeded`, and `running -> failed`; terminal Jobs SHALL have no successors and same-state transitions SHALL be illegal.

#### Scenario: Start pending Job

- **GIVEN** a `pending` Job
- **WHEN** it legally transitions to `running`
- **THEN** its start time SHALL be set
- **AND** its result, error, and completion time SHALL remain absent

#### Scenario: Complete running Job successfully

- **GIVEN** a `running` Job
- **WHEN** it legally transitions to `succeeded` with a structured result object
- **THEN** its completion time and result SHALL be persisted
- **AND** its error SHALL remain absent

#### Scenario: Complete running Job with failure

- **GIVEN** a `running` Job
- **WHEN** it legally transitions to `failed` with a non-empty bounded error
- **THEN** its completion time and error SHALL be persisted
- **AND** its result SHALL remain absent

#### Scenario: Reject illegal transition

- **GIVEN** a Job whose current state cannot legally precede the requested state
- **WHEN** the transition is requested
- **THEN** the system SHALL raise a typed illegal-transition error
- **AND** SHALL NOT mutate or flush a lifecycle update for that Job

### Requirement: Keep lifecycle fields coherent

Job payload and result values SHALL be structured JSON objects using only JSON-compatible values. Empty payload/result objects SHALL be allowed. State-specific result, error, start, and completion fields SHALL satisfy the closed lifecycle contract, and lifecycle timestamps SHALL be timezone-aware UTC instants in non-decreasing order.

#### Scenario: Reject incoherent successful state

- **WHEN** a Job is persisted as `succeeded` without a result, with an error, without a start/completion time, or with reversed lifecycle timestamps
- **THEN** persistence SHALL reject the incoherent state

#### Scenario: Reject incoherent failed state

- **WHEN** a Job is persisted as `failed` without a non-empty error, with a result, without a start/completion time, or with reversed lifecycle timestamps
- **THEN** persistence SHALL reject the incoherent state

#### Scenario: Reject unsupported JSON value

- **WHEN** a Job payload or result contains a non-JSON value, non-string object key, or non-finite number
- **THEN** validation SHALL reject it before persistence

### Requirement: Provide deterministic internal persistence operations

The internal persistence boundary SHALL support Job creation, lookup by Job identifier, deterministic listing for one MarketingRun, and lifecycle transition. Missing lookup SHALL return no Job, missing transition targets SHALL raise a typed not-found error, and run-scoped listing SHALL order by creation time and then Job identifier.

#### Scenario: Load missing Job

- **WHEN** a Job identifier is not persisted and a read lookup is requested
- **THEN** the operation SHALL return no Job

#### Scenario: Transition missing Job

- **WHEN** a lifecycle transition targets an unknown Job identifier
- **THEN** the operation SHALL raise a typed not-found error

#### Scenario: List run Jobs

- **GIVEN** multiple Jobs associated with one MarketingRun
- **WHEN** those Jobs are listed
- **THEN** only Jobs for that run SHALL be returned
- **AND** their order SHALL be ascending creation time followed by ascending Job identifier

#### Scenario: Duplicate Job identifier

- **GIVEN** a persisted Job identifier
- **WHEN** a second Job is flushed with the same identifier
- **THEN** the database SHALL reject the duplicate
- **AND** no second Job row SHALL be created

### Requirement: Preserve caller-owned transactions

Job persistence mutations SHALL add or flush within the supplied database session and SHALL NOT commit or roll back independently. Lifecycle transitions SHALL serialize concurrent mutation using a row-level database lock held by the caller transaction.

#### Scenario: Create without autonomous commit

- **WHEN** a valid Job is created through the persistence boundary
- **THEN** the Job MAY be flushed for database validation
- **AND** no autonomous commit SHALL occur

#### Scenario: Atomically update Job and MarketingRun

- **GIVEN** a Job mutation and a related MarketingRun state mutation in one caller-owned transaction
- **WHEN** every operation succeeds and the caller commits
- **THEN** both mutations SHALL become durable atomically

#### Scenario: Roll back a partial unit of work

- **GIVEN** Job persistence was flushed but another operation in the caller transaction fails
- **WHEN** the caller rolls back
- **THEN** no partial Job or MarketingRun mutation from that transaction SHALL remain durable

#### Scenario: Concurrent transition

- **GIVEN** two transactions attempt to transition the same Job
- **WHEN** the first transaction locks and completes the legal transition
- **THEN** the second SHALL evaluate the state after lock acquisition
- **AND** SHALL apply a transition only if it is still legal

### Requirement: Preserve relational ownership and deletion behavior

Deleting a MarketingRun SHALL cascade-delete its run-owned Jobs. Deleting a user SHALL set the owner of a user-owned Job to null while retaining the Job. Existing MarketingRun and MarketingArtifact rows and constraints SHALL otherwise remain unchanged.

#### Scenario: Delete MarketingRun

- **GIVEN** a MarketingRun with owned Jobs and MarketingArtifacts
- **WHEN** the MarketingRun is deleted
- **THEN** its Jobs SHALL be deleted through the Job foreign-key contract
- **AND** existing MarketingArtifact cascade behavior SHALL remain unchanged

#### Scenario: Delete user-owned Job owner

- **GIVEN** a runless Job associated directly with a user
- **WHEN** that user is deleted
- **THEN** the Job SHALL remain durable with no user owner

### Requirement: Add one reversible schema revision

The capability SHALL be introduced by one additive migration from the current single migration head. Upgrade SHALL create only the approved Job structures and indexes, and downgrade SHALL remove only those structures in dependency-safe order.

#### Scenario: Upgrade from current head

- **GIVEN** a database at revision `20260814_0003`
- **WHEN** the Job migration is applied
- **THEN** the approved Job table, constraints, foreign keys, and indexes SHALL exist
- **AND** existing tables and rows SHALL remain unchanged

#### Scenario: Downgrade Job revision

- **GIVEN** a database with no later dependent revision
- **WHEN** the Job migration is downgraded one revision
- **THEN** only the Job indexes and table SHALL be removed
- **AND** the database SHALL return to revision `20260814_0003`

### Requirement: Remain persistence-only and backward compatible

Adding durable Job persistence SHALL NOT enqueue, claim, execute, retry, cancel, time out, deliver, or deduplicate work. It SHALL NOT alter existing public API/Telegram contracts, synchronous task behavior, Marketing Orchestrator planning, Quality Gates behavior, Module Registry metadata, MarketingRun/MarketingArtifact behavior, or model/QC call counts.

#### Scenario: Persist Job before queue infrastructure exists

- **WHEN** a Job is committed before any later queue/worker integration is installed
- **THEN** the Job SHALL be durable in PostgreSQL
- **AND** no Redis publication, worker claim, polling, module execution, LLM/QC call, or delivery SHALL occur

#### Scenario: Existing runtime flow

- **WHEN** an existing chat, task, image, brand-profile, direct-agent, or Telegram flow runs
- **THEN** its request/response contract and execution path SHALL remain unchanged
- **AND** it SHALL NOT require the Job persistence capability
