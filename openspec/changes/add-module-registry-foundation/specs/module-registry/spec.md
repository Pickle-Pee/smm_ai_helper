## ADDED Requirements

### Requirement: Canonical module registry

The system SHALL provide one canonical, versioned registry of marketing module descriptors.

#### Scenario: Resolve canonical module

- **WHEN** routing requests a registered canonical module ID
- **THEN** the registry returns exactly one immutable descriptor
- **AND** the descriptor contains its declared applicability, inputs, outputs, tools, gates and handoffs

#### Scenario: Reject duplicate ID

- **WHEN** two descriptors declare the same canonical module ID
- **THEN** registry validation fails before task execution

### Requirement: Alias resolution

The system SHALL resolve every registered alias to exactly one canonical module ID.

#### Scenario: Resolve alias

- **WHEN** routing requests a registered alias
- **THEN** the registry returns the descriptor of its canonical module
- **AND** no second module descriptor is created

#### Scenario: Reject alias collision

- **WHEN** an alias resolves ambiguously or collides with another canonical ID
- **THEN** registry validation fails

### Requirement: Module activation contract

The system SHALL define an internal activation contract containing the module objective, relevant context, known facts, upstream findings, evidence, assumptions, confidence, constraints, available tools and open questions.

#### Scenario: Build minimal activation packet

- **WHEN** a module is selected
- **THEN** only context relevant to that module objective is included
- **AND** unrelated conversation content is not required by the contract

### Requirement: Module return contract

The system SHALL normalize module results using a status and structured fields for summary, findings, evidence, assumptions, hypotheses, recommendations, risks, confidence, open questions, strategic issues and handoff recommendation.

#### Scenario: Return limited result

- **WHEN** a module completes with material evidence limitations
- **THEN** it returns `PASS_WITH_LIMITATIONS`
- **AND** the limitations remain represented in evidence, assumptions, confidence or open questions

### Requirement: Registry is not an execution engine

The registry SHALL NOT execute modules, persist project state or orchestrate multi-step workflows.

#### Scenario: Read descriptor

- **WHEN** an execution component queries the registry
- **THEN** the registry returns metadata only
- **AND** no model call, database write or queue operation is initiated

### Requirement: Compatibility

Introducing the registry SHALL preserve existing public APIs, database schema and single-task pipeline behavior.

#### Scenario: Existing standalone agent

- **WHEN** an existing standalone agent is selected after registry integration
- **THEN** it continues through the existing execution path
- **AND** the registry does not create a parallel runner

