# Task Execution Specification

## Purpose

Define the current public behavior for executing one marketing-agent task through `/tasks`.

## Requirements

### Requirement: Start a supported task
The system SHALL start tasks only for supported agent types and SHALL return either a clarification response or a completed result.

#### Scenario: Supported task starts
- **GIVEN** a supported agent type
- **WHEN** a client calls `POST /tasks/start`
- **THEN** the system SHALL create or resolve the user when user data is supplied
- **AND** SHALL execute the task pipeline
- **AND** SHALL return `need_info` or `done`

#### Scenario: Unknown agent type
- **WHEN** a client starts a task with an unsupported agent type
- **THEN** the system SHALL return HTTP 404

### Requirement: Continue clarification sessions
The system SHALL persist task-session state while clarification is required and SHALL allow a client to continue it by session ID.

#### Scenario: Answer known session
- **GIVEN** an existing task session
- **WHEN** a client calls `POST /tasks/answer` with the requested key and value
- **THEN** the system SHALL continue the same task flow
- **AND** SHALL return `need_info` or `done`

#### Scenario: Answer unknown session
- **WHEN** a client answers a session that does not exist
- **THEN** the system SHALL return HTTP 404

### Requirement: Persist completed task history
The system SHALL persist completed task results and SHALL expose task history retrieval.

#### Scenario: Completed task is saved
- **WHEN** a task reaches `done`
- **THEN** its result SHALL be persisted in task history

#### Scenario: User task history is requested
- **WHEN** a client requests recent tasks by Telegram user ID
- **THEN** the system SHALL return the user's recent persisted tasks up to the requested limit.