## Purpose

Provide a versioned, immutable product-module metadata registry that downstream domain components can inspect safely without changing or duplicating current agent execution.

## ADDED Requirements

### Requirement: Canonical versioned registry

The system SHALL load the single canonical runtime registry from the app-owned `v1.0.0` structured resource and SHALL expose exactly one immutable descriptor for each of the fifteen expected canonical module IDs.

#### Scenario: Load canonical set
- **WHEN** registry version `1.0.0` is loaded
- **THEN** the registry contains exactly the fifteen expected canonical IDs
- **AND** each canonical ID has exactly one immutable descriptor
- **AND** the declared source version is `1.0.0`

#### Scenario: Reject invalid canonical set
- **WHEN** the resource has a duplicate, missing, or unexpected canonical ID, or not exactly fifteen descriptors
- **THEN** validation fails before registry use

### Requirement: Immutable typed descriptor

Each descriptor SHALL define its canonical ID, module type, applicability, classified input requirements, declared outputs, supported tool flags, quality gates, aliases, handoffs, authority limitations, availability status, and optional execution binding using validated internal domain types.

#### Scenario: Read descriptor
- **WHEN** a consumer retrieves a canonical descriptor
- **THEN** all required fields are non-empty and enum/capability values are valid
- **AND** descriptor and registry collections cannot be mutated

#### Scenario: Reject mutation
- **WHEN** a consumer attempts to mutate a descriptor or registry collection
- **THEN** the mutation is rejected
- **AND** subsequent lookup returns unchanged metadata

### Requirement: Deterministic alias resolution

The system SHALL normalize lookup values by trimming leading/trailing Unicode whitespace, applying Unicode case folding, and replacing every contiguous run of Unicode whitespace, hyphens, or underscores with one underscore. Canonical IDs and aliases SHALL share one normalized namespace.

#### Scenario: Resolve alias
- **WHEN** a registered alias is supplied with differences only in surrounding whitespace, case, or hyphen/underscore/whitespace separators
- **THEN** lookup returns its one canonical immutable descriptor
- **AND** no additional descriptor is created

#### Scenario: Reject invalid alias namespace
- **WHEN** a normalized alias is empty, duplicated, collides with any normalized canonical ID, or resolves ambiguously
- **THEN** validation fails before registry use

### Requirement: Valid references and capabilities

The registry SHALL accept only supported capability flags and existing canonical handoff targets and SHALL prohibit self-handoffs.

#### Scenario: Reject invalid descriptor references
- **WHEN** a descriptor declares an unsupported tool flag, nonexistent handoff target, or self-handoff
- **THEN** validation fails before registry use

### Requirement: Separate availability and result status

The domain contract SHALL represent module implementation availability separately from module execution result status.

#### Scenario: Represent metadata-only module
- **WHEN** a module has no exact executable implementation
- **THEN** its availability is `metadata_only`
- **AND** no execution binding is declared
- **AND** this state is not represented as `PASS`, `PASS_WITH_LIMITATIONS`, `FAIL`, or `BLOCKED`

#### Scenario: Represent execution result
- **WHEN** a future execution component reports a module outcome
- **THEN** its internal result status is one of `PASS`, `PASS_WITH_LIMITATIONS`, `FAIL`, or `BLOCKED`
- **AND** that status does not change registry availability metadata

### Requirement: Optional execution bindings are metadata only

An execution binding SHALL be permitted only for compatibility classified as `exact`, SHALL reference an executable ID known to the existing execution registry, and SHALL NOT execute or select the agent. Module aliases SHALL NOT become executable-agent aliases.

#### Scenario: Validate exact binding
- **WHEN** a descriptor declares an execution binding
- **THEN** validation confirms exact compatibility evidence and a known executable agent ID
- **AND** lookup returns the binding as metadata without executing it

#### Scenario: Reject invalid binding
- **WHEN** a metadata-only module declares a binding, an execution-bound module lacks a binding, or a binding targets an unknown or non-exact agent
- **THEN** validation fails before registry use

#### Scenario: Version 1.0.0 has no bindings
- **WHEN** the initial registry is loaded
- **THEN** all fifteen descriptors are metadata-only
- **AND** no current standalone agent is declared an exact executable binding

### Requirement: Internal activation and return contracts

The system SHALL define internal activation and return contracts for future module consumers without replacing public DTOs or current agent/task result contracts.

#### Scenario: Build activation contract
- **WHEN** a future internal consumer prepares module activation data
- **THEN** the contract can represent objective, user goal, required output, relevant context, known facts, upstream findings, evidence, assumptions, confidence, constraints, available tools, and open questions

#### Scenario: Build limited return contract
- **WHEN** a future module result has material evidence limitations
- **THEN** the internal result may use `PASS_WITH_LIMITATIONS`
- **AND** limitations remain represented in evidence, assumptions, confidence, or open questions
- **AND** no public API or current agent result format is modified

### Requirement: Registry is read-only metadata, not execution

The registry SHALL NOT instantiate agents, select routes, execute modules, persist business state, orchestrate workflows, or initiate model, database, queue, or QC operations.

#### Scenario: Query registry
- **WHEN** a consumer performs descriptor or alias lookup
- **THEN** only immutable metadata is returned
- **AND** no execution or external side effect occurs

### Requirement: Existing execution behavior remains unchanged

Introducing the registry SHALL preserve the existing five-agent execution registry, task-routing decisions, runner behavior, single-task pipeline, public APIs, database schema, Telegram behavior, and model/QC call counts.

#### Scenario: Run existing standalone agent
- **WHEN** `strategy`, `content`, `analytics`, `promo`, or `trends` is selected through the current task path
- **THEN** the existing execution registry, router, runner, and pipeline behavior is unchanged
- **AND** product module aliases do not alter executable agent selection

### Requirement: Deterministic initial-import verification

The initial resource SHALL be verifiable against approved source material for the expected IDs, one descriptor per ID, aliases, classified inputs, outputs, tool flags, quality gates, handoffs, authority limitations, availability/binding state, and source version. Verification MAY record a normalized JSON checksum as evidence.

#### Scenario: Record import evidence
- **WHEN** the v1.0.0 initial import is implemented and verified
- **THEN** results are recorded in the durable verification document
- **AND** the document does not become another runtime descriptor source
