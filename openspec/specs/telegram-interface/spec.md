# Telegram Interface Specification

## Purpose

Define the current Telegram bot interface behavior while keeping marketing logic in the backend.

## Requirements

### Requirement: Provide a simple entry point
The Telegram bot SHALL provide a start message that explains representative marketing requests the user can send.

#### Scenario: User starts the bot
- **WHEN** the user invokes `/start`
- **THEN** the bot SHALL explain that it can help with strategy, content, advertising/audit, URL analysis, and creative generation using example prompts

### Requirement: Delegate free-text chat to backend
The Telegram bot SHALL delegate ordinary free-text chat messages to the backend chat API.

#### Scenario: Text message is received
- **WHEN** a user sends a non-command text message
- **THEN** the bot SHALL call the backend `/chat/message` endpoint
- **AND** SHALL identify the user using `tg:<telegram_id>`
- **AND** SHALL render the returned reply, follow-up question, actions, and available images

### Requirement: Render backend action suggestions
The Telegram bot SHALL expose backend suggestion actions as callback buttons when actions are present.

#### Scenario: User selects an action
- **GIVEN** a still-available action mapping
- **WHEN** the user presses its callback button
- **THEN** the bot SHALL submit the mapped action text through the same backend chat flow

### Requirement: Handle backend failures without exposing internals
The Telegram bot SHALL present a user-safe error message when a backend chat request fails.

#### Scenario: Backend returns an error
- **WHEN** the backend chat request fails or returns an error status
- **THEN** the bot SHALL notify the user that the message could not be processed
- **AND** SHALL NOT expose an internal stack trace.