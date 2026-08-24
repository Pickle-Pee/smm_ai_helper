## ADDED Requirements

### Requirement: Request interpretation

The orchestrator SHALL represent the requested output, decision goal, business goal, intent, object, response depth and constraints before building a multi-module plan.

#### Scenario: Distinguish output from goal

- **WHEN** a user requests a creative while describing a broader sales problem
- **THEN** the interpretation preserves the requested creative output
- **AND** records the broader decision or business goal separately

### Requirement: Minimum sufficient plan

The orchestrator SHALL select the minimum set of registered modules capable of producing a sufficiently reliable result.

#### Scenario: Simple request

- **WHEN** one registered module can complete the requested scope with available context
- **THEN** the plan contains one execution node
- **AND** unrelated modules are not added for completeness

#### Scenario: Complex request

- **WHEN** the requested result depends on outputs from multiple modules
- **THEN** the plan contains only the required nodes and dependencies

### Requirement: Dependency-aware planning

The orchestrator SHALL distinguish independent work from sequential dependencies.

#### Scenario: Parallelizable analyses

- **WHEN** market and competitor analyses use independent inputs
- **THEN** the plan may mark them parallelizable

#### Scenario: Positioning depends on analyses

- **WHEN** positioning requires upstream market or competitor findings
- **THEN** the positioning node depends on those upstream nodes

### Requirement: Scoped context packet

The orchestrator SHALL build a context packet containing only information relevant to a module objective.

#### Scenario: Exclude unrelated context

- **WHEN** a module is activated
- **THEN** its packet contains relevant project context, known facts, upstream findings, evidence, assumptions, confidence, constraints, tools and open questions
- **AND** unrelated conversation history is not required

### Requirement: Data sufficiency

The orchestrator SHALL classify critical input sufficiency as sufficient, partial or insufficient.

#### Scenario: Missing blocking input

- **WHEN** a blocking input cannot be obtained from existing context or tools
- **THEN** the plan is blocked before the dependent node
- **AND** the orchestrator requests no more than three decision-changing clarifications

#### Scenario: Missing optional input

- **WHEN** an optional input is missing
- **THEN** the plan may continue with an explicit limitation

### Requirement: Plan validation

The orchestrator SHALL reject plans containing unknown modules, unresolved aliases, dependency cycles or invalid blocking dependencies.

#### Scenario: Cyclic plan

- **WHEN** generated dependencies contain a cycle
- **THEN** plan validation fails before execution

### Requirement: Architectural isolation

The orchestrator SHALL NOT convert `TaskPipelineService` into a multi-step workflow engine.

#### Scenario: Existing single task

- **WHEN** a standalone single-task request is processed
- **THEN** it continues through the existing single-task pipeline

