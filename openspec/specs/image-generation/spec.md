# Image Generation Specification

## Purpose

Define the current image generation API and retrieval behavior.

## Requirements

### Requirement: Generate marketing images
The system SHALL expose an image-generation endpoint that returns references to generated images.

#### Scenario: Valid generation request
- **WHEN** a client calls `POST /images/generate` with a valid image request
- **THEN** the system SHALL generate between one and three image variants
- **AND** SHALL return status `done`, the selected mode/preset, and image URLs

### Requirement: Use brand and overlay context
The system SHALL allow image generation to use optional brand context and optional overlay text.

#### Scenario: Brand context is supplied
- **WHEN** a request includes brand information
- **THEN** image brief generation SHALL receive that context

#### Scenario: Overlay content is supplied
- **WHEN** a request includes overlay content
- **THEN** the image pipeline MAY render or incorporate that overlay according to the resolved generation mode

### Requirement: Retrieve generated image
The system SHALL expose generated PNG images by image ID while the underlying image exists in configured storage.

#### Scenario: Existing image is requested
- **WHEN** a client calls `GET /images/{image_id}.png` for a stored image
- **THEN** the system SHALL return the image file

#### Scenario: Unknown image is requested
- **WHEN** the requested image cannot be resolved from storage
- **THEN** the system SHALL return HTTP 404.