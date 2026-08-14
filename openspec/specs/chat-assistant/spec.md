# Chat Assistant Specification

## Purpose

Define the current conversational assistant behavior exposed through `/chat/message`.

## Requirements

### Requirement: Preserve chat memory
The system SHALL persist user and assistant messages and SHALL use recent conversation context when generating a response.

#### Scenario: Normal chat message
- **WHEN** a user sends a permitted chat message
- **THEN** the user message SHALL be stored
- **AND** recent conversation context SHALL be loaded
- **AND** the returned assistant reply SHALL be stored

### Requirement: Apply contextual brand information
The system SHALL combine persistent brand profile context with non-empty temporary conversation facts when generating chat responses.

#### Scenario: Profile and conversation facts exist
- **GIVEN** a user with a saved brand profile
- **AND** non-empty facts extracted from the current conversation
- **WHEN** the assistant generates a response
- **THEN** persistent profile context SHALL be used as the base
- **AND** non-empty conversation facts MAY temporarily override or extend that context
- **AND** empty temporary values SHALL NOT erase persistent profile values

### Requirement: Use URL context when available
The system SHALL analyze supported URL or handle targets present in a chat message and make the resulting summaries available to response generation.

#### Scenario: Message contains analyzable target
- **WHEN** a message contains a supported URL or social handle target
- **THEN** the assistant SHALL attempt URL analysis
- **AND** SHALL pass available URL summaries into context/response generation

### Requirement: Support optional image responses
The system SHALL support image-generation intent without changing the base `/chat/message` response contract.

#### Scenario: User requests an image
- **WHEN** the message is recognized as an image request
- **THEN** the system SHALL attempt image generation
- **AND** MAY return an `image` payload together with reply, follow-up question, and actions

### Requirement: Block out-of-scope requests safely
The system SHALL return a normalized blocked response when the scope guard rejects a message.

#### Scenario: Scope guard blocks message
- **WHEN** the scope guard rejects a user message
- **THEN** the system SHALL not continue normal URL/context/image processing
- **AND** SHALL return a normalized assistant response indicating the request cannot be handled.