# URL Analysis Specification

## Purpose

Define the current lightweight URL/social-target extraction and analysis behavior used by chat.

## Requirements

### Requirement: Extract a bounded target set
The system SHALL extract at most three unique analyzable targets from a user message.

#### Scenario: Multiple URLs are present
- **WHEN** a message contains multiple URLs
- **THEN** the system SHALL normalize and de-duplicate them while preserving order
- **AND** SHALL process at most three targets

#### Scenario: Social handle is present
- **WHEN** a message contains a supported Telegram or Instagram handle form
- **THEN** the system MAY resolve the handle to a platform URL using the message context

### Requirement: Return structured analysis summaries
The system SHALL return structured per-target summaries without making a single fetch failure crash the whole chat flow.

#### Scenario: HTML target is available
- **WHEN** an HTML page can be fetched
- **THEN** the summary SHALL contain available metadata and extracted page signals suitable for downstream analysis

#### Scenario: Target fetch fails
- **WHEN** a target cannot be fetched or is blocked
- **THEN** the analyzer SHALL return a structured unsuccessful summary with warning/error information

### Requirement: Cache URL analysis
The system SHALL cache URL analysis results in persistent URL cache storage when a database session is available.

#### Scenario: Valid unexpired cache entry exists
- **WHEN** the same normalized target is analyzed before its cache expiration
- **THEN** the analyzer SHALL be able to reuse the cached summary instead of requiring a fresh fetch.