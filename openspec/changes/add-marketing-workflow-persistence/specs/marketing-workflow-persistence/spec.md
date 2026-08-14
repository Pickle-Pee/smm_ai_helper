# Marketing Workflow Persistence Delta Specification

## ADDED Requirements

### Requirement: Persist a marketing workflow run
The system SHALL persist a durable marketing workflow run independently from standalone task-session records.

#### Scenario: Create a new marketing run
- **GIVEN** a workflow type and initial input context
- **WHEN** a new marketing workflow run is created
- **THEN** the system SHALL assign a stable run identifier
- **AND** SHALL persist the workflow type, lifecycle status, input context, creation time, and update time
- **AND** the run SHALL remain loadable after the creating process ends

#### Scenario: Load an existing marketing run
- **GIVEN** a persisted marketing run identifier
- **WHEN** the persistence layer loads the run
- **THEN** it SHALL return the persisted lifecycle and state fields for that run

### Requirement: Track marketing run lifecycle state
The system SHALL persist the current lifecycle status and optional current workflow step for each marketing run.

#### Scenario: Advance run state
- **GIVEN** an existing marketing run
- **WHEN** its status, current step, workflow state, or error information is updated
- **THEN** the updated values SHALL be persisted
- **AND** the update timestamp SHALL reflect the change

#### Scenario: Failed run preserves diagnostic state
- **GIVEN** an existing marketing run
- **WHEN** the run is marked failed
- **THEN** the system SHALL be able to persist an error description together with the failed status
- **AND** previously persisted run input and artifacts SHALL remain available

### Requirement: Persist named workflow artifacts
The system SHALL persist structured artifacts produced by marketing workflow steps and associate each artifact with exactly one marketing run.

#### Scenario: Create a workflow artifact
- **GIVEN** an existing marketing run
- **WHEN** a step persists an artifact with an artifact key, artifact type, and structured payload
- **THEN** the artifact SHALL be stored under that run
- **AND** SHALL remain retrievable by the run and artifact key

#### Scenario: Retry writes the same logical artifact
- **GIVEN** an existing artifact with a run identifier and artifact key
- **WHEN** the same logical artifact is persisted again for that run
- **THEN** the system SHALL update the existing artifact payload and metadata rather than create a second artifact with the same run identifier and artifact key

#### Scenario: List artifacts for a run
- **GIVEN** a marketing run with one or more persisted artifacts
- **WHEN** its artifacts are requested
- **THEN** the system SHALL return the artifacts associated with that run in deterministic order

### Requirement: Associate runs with known users without requiring user identity
The system SHALL support both user-owned and anonymous marketing workflow runs.

#### Scenario: Known user starts a run
- **GIVEN** an existing persisted user
- **WHEN** a marketing run is created for that user
- **THEN** the run SHALL reference that user

#### Scenario: Anonymous run is created
- **WHEN** a marketing run is created without a persisted user
- **THEN** the run SHALL still be persistable and loadable without a user reference

### Requirement: Preserve current public contracts
The persistence change SHALL NOT alter existing public chat, task, image, brand-profile, or Telegram response contracts.

#### Scenario: Existing interfaces remain unchanged
- **WHEN** the marketing workflow persistence capability is added
- **THEN** existing `/chat`, `/tasks`, `/images`, and `/brand-profile` request/response contracts SHALL remain compatible
- **AND** existing Telegram handlers SHALL NOT require the new persistence capability to process their current flows
