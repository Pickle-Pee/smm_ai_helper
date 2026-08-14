# Brand Profile Specification

## Purpose

Define persistent brand context owned by a registered Telegram user.

## Requirements

### Requirement: One persistent profile per user
The system SHALL store at most one BrandProfile for each persisted user.

#### Scenario: Profile exists
- **GIVEN** a persisted user with a BrandProfile
- **WHEN** the profile is loaded
- **THEN** the system SHALL expose the stored brand fields for that user

### Requirement: Read brand profile by Telegram ID
The system SHALL expose a profile-read endpoint by Telegram user ID.

#### Scenario: Existing profile is requested
- **WHEN** `GET /brand-profile/{telegram_id}` identifies a user with a profile
- **THEN** the system SHALL return that profile

#### Scenario: Profile is missing
- **WHEN** no profile exists for the requested Telegram ID
- **THEN** the system SHALL return HTTP 404

### Requirement: Partially update brand profile
The system SHALL allow partial updates of supported brand profile fields for an existing user.

#### Scenario: Valid patch
- **GIVEN** an existing user
- **WHEN** `PATCH /brand-profile/{telegram_id}` contains supported fields
- **THEN** the system SHALL create or update the user's profile with only the supplied fields

#### Scenario: Empty patch
- **WHEN** the patch contains no fields
- **THEN** the system SHALL return HTTP 400

#### Scenario: Unknown field
- **WHEN** the request contains an unsupported profile field
- **THEN** request validation SHALL reject it

### Requirement: Resolve Telegram chat identifiers
The system SHALL resolve both plain numeric Telegram IDs and `tg:<telegram_id>` chat identifiers for profile context lookup.

#### Scenario: Prefixed chat identifier
- **WHEN** chat context lookup receives `tg:12345` or an equivalent case-insensitive prefix
- **THEN** it SHALL resolve Telegram ID `12345`

#### Scenario: Unsupported chat identifier
- **WHEN** chat context lookup receives a non-Telegram identifier such as `anonymous`
- **THEN** it SHALL return empty profile context without performing a Telegram profile lookup.