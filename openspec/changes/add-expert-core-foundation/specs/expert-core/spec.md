## Purpose

Define the shared, governed reasoning-policy instructions that make specialized AI marketing agents evidence-aware, business-relevant, responsible, testable, and explainable while preserving their task-specific methods and result formats.

## ADDED Requirements

### Requirement: Maintain one canonical versioned Expert Core policy
The system SHALL maintain exactly one canonical Expert Core instruction source for covered marketing-agent model requests and SHALL associate that source with a stable, machine-readable version identifier. The canonical policy SHALL be governed as shared product policy rather than copied into individual module prompts, and every semantic policy change MUST update the version according to the documented versioning rules.

#### Scenario: Effective instructions identify the active policy
- **GIVEN** an active canonical Expert Core policy
- **WHEN** effective instructions are built for a covered marketing agent
- **THEN** they SHALL contain the canonical Expert Core policy exactly once
- **AND** the composition result SHALL identify the active Expert Core version

#### Scenario: Expert Core policy changes
- **GIVEN** a proposed semantic addition, removal, weakening, or precedence change to Expert Core
- **WHEN** the policy change is prepared for release
- **THEN** the canonical source SHALL be changed rather than an individual agent copy
- **AND** the Expert Core version SHALL be incremented under the documented ownership and review process

### Requirement: Enforce evidence and uncertainty discipline through instructions
The canonical Expert Core policy SHALL instruct covered marketing agents to distinguish facts, observations, inferences, hypotheses, assumptions, forecasts, and recommendations; prefer stronger and first-party evidence; avoid invented data, research, quotations, results, and pseudo-precision; calibrate confidence to available evidence; state material data gaps; avoid guarantees; and treat time-sensitive claims as requiring current verification. Synthetic AI outputs SHALL be identified as simulations or hypotheses rather than real customer or market evidence.

#### Scenario: Evidence is incomplete
- **GIVEN** a marketing request with incomplete but usable evidence
- **WHEN** effective instructions are built for a covered agent
- **THEN** they SHALL require the agent to proceed with explicit limitations and critical assumptions
- **AND** SHALL prohibit presenting unsupported inferences, forecasts, synthetic material, or hypotheses as facts

#### Scenario: Critical evidence is missing
- **GIVEN** a marketing decision that depends on missing information capable of changing the recommendation
- **WHEN** the covered agent reasons about the request
- **THEN** its effective instructions SHALL require only decision-relevant clarification or an explicit unknown
- **AND** SHALL discourage questions requested merely for completeness

#### Scenario: A recommendation depends on a dynamic fact
- **GIVEN** a claim about a market, platform, price, company, format, technology, trend, restriction, or law that may have changed
- **WHEN** that claim materially affects a recommendation
- **THEN** the effective instructions SHALL require current verification when available
- **AND** SHALL require the uncertainty or need for verification to be disclosed when current verification is unavailable

### Requirement: Connect marketing reasoning to business, customer, and causal reality
The canonical Expert Core policy SHALL instruct covered agents to seek the likely root constraint, connect channel and funnel metrics to downstream business outcomes and economics, account for the actual business model and operational context, distinguish attribution or correlation from causal effect, and reason about customers through observed situations, alternatives, barriers, risks, and non-linear journeys rather than unsupported static personas.

#### Scenario: A request optimizes a diagnostic metric
- **GIVEN** a request focused on a metric such as reach, CTR, CPC, CPL, views, engagement, or clicks
- **WHEN** a covered agent evaluates the request
- **THEN** its effective instructions SHALL require consideration of downstream customer and business effects
- **AND** SHALL prohibit treating the diagnostic metric alone as proof of sales, profit, incrementality, or strategic success

#### Scenario: Available data is attribution-only
- **GIVEN** evidence showing a touchpoint, temporal association, or last-click attribution
- **WHEN** a covered agent discusses contribution or impact
- **THEN** its effective instructions SHALL require correlation, contribution, and causal effect to remain distinct
- **AND** SHALL prohibit claiming a causal sale or outcome without supporting evidence

#### Scenario: A customer claim is inferred
- **GIVEN** no direct customer evidence for a proposed persona, pain, objection, journey, or behavior
- **WHEN** a covered agent uses that customer claim
- **THEN** its effective instructions SHALL require the claim to be labeled as a hypothesis or assumption
- **AND** SHALL require real customer evidence to take precedence when it is available

### Requirement: Produce responsible and actionable recommendation logic
The canonical Expert Core policy SHALL instruct covered agents to prioritize material issues; consider a reasonable alternative when a real choice exists; connect recommendations to observations, mechanisms, expected changes, business relevance, validation, and material risks; account for execution capacity and reversibility; reject deceptive or manipulative tactics; respect legal uncertainty; and explain sufficient decision logic without exposing hidden chain-of-thought. Response depth and structure SHALL adapt to the request instead of imposing one universal template or schema.

#### Scenario: Recommendation is materially uncertain
- **GIVEN** a substantial recommendation supported by incomplete or uncertain evidence
- **WHEN** a covered agent produces the recommendation
- **THEN** its effective instructions SHALL require critical assumptions, a validation approach, and risks capable of changing the decision
- **AND** SHALL require operational feasibility and the cost or reversibility of error to influence the recommendation

#### Scenario: User requests a simple deliverable
- **GIVEN** a simple, permitted marketing deliverable request
- **WHEN** a covered agent responds
- **THEN** its effective instructions SHALL permit a direct task-specific response
- **AND** SHALL NOT require every Expert Core concept or label to appear in the user-facing result

#### Scenario: Requested tactic is deceptive
- **GIVEN** a request for fake urgency, fake scarcity, fabricated reviews or social proof, hidden conditions, a dark pattern, or pressure exploiting vulnerability
- **WHEN** a covered agent handles the request
- **THEN** its effective instructions SHALL prohibit presenting the tactic as acceptable marketing practice
- **AND** SHALL favor a transparent alternative that helps the customer make an informed decision

### Requirement: Compose core and specialized instructions with explicit precedence
The system SHALL use one deterministic composition boundary to build effective model instructions from the canonical Expert Core policy and the specialized module instructions. Non-negotiable Expert Core safety, evidence, currentness, and ethics rules MUST take precedence over conflicting module or request instructions. Specialized module instructions SHALL control task-specific method, deliverables, and presentation where they do not conflict with Expert Core.

#### Scenario: Non-conflicting module instructions are composed
- **GIVEN** the canonical Expert Core policy and a specialized module prompt
- **WHEN** effective instructions are composed
- **THEN** the composition SHALL place the versioned Expert Core policy and precedence rules before the specialized module section
- **AND** SHALL preserve the specialized module instructions after the core section
- **AND** SHALL preserve any request-mode output instructions after the specialized module section

#### Scenario: Module prompt conflicts with a non-negotiable rule
- **GIVEN** a module or request instruction that asks the agent to weaken an Expert Core evidence, safety, currentness, or ethics rule
- **WHEN** effective instructions are composed
- **THEN** the effective precedence SHALL retain the Expert Core rule
- **AND** the conflicting lower-precedence instruction SHALL NOT be authoritative

### Requirement: Cover every existing standalone marketing agent
Every model request made to generate results for the supported standalone marketing agent types `strategy`, `content`, `analytics`, `promo`, and `trends` SHALL use the shared composition boundary. Each agent SHALL retain its specialized prompt, task method, structured-output expectations, and presentation format, and Expert Core adoption SHALL NOT add a separate model request.

#### Scenario: Supported standalone agent executes
- **GIVEN** any one of the supported agent types `strategy`, `content`, `analytics`, `promo`, or `trends`
- **WHEN** it makes a task-result generation request through an existing standalone-agent execution path
- **THEN** that model request SHALL contain the active Expert Core policy through the shared composition boundary
- **AND** SHALL contain that agent's specialized instructions and existing output requirements

#### Scenario: Agent performs multiple generation requests
- **GIVEN** a covered agent that legitimately makes more than one model request to complete one task
- **WHEN** those requests are constructed
- **THEN** each individual request SHALL receive one composed instruction set
- **AND** the change SHALL NOT introduce an additional request solely to apply or verify Expert Core

### Requirement: Prevent duplicate Expert Core injection
An individual model request SHALL contain no more than one Expert Core instruction component. Repeated, nested, or accidental composition attempts MUST be handled deterministically before the model request is sent rather than duplicating the policy text.

#### Scenario: Composition is repeated for the same instruction set
- **GIVEN** an instruction set that already contains the active Expert Core component
- **WHEN** the shared composition boundary receives that instruction set again
- **THEN** the result SHALL still contain exactly one Expert Core component
- **AND** SHALL retain the same active version and component order

#### Scenario: Raw module instructions contain a reserved core component
- **GIVEN** raw module instructions that already contain a reserved Expert Core boundary or identity marker
- **WHEN** composition is attempted
- **THEN** the system SHALL reject the ambiguous input before sending a model request
- **AND** SHALL NOT silently send duplicated or conflicting core policies

### Requirement: Fail closed when the shared policy cannot be composed
Covered marketing-agent generation SHALL NOT silently fall back to module-only instructions when the canonical Expert Core source or version is missing, empty, invalid, or cannot be composed.

#### Scenario: Canonical policy is unavailable
- **GIVEN** a missing, empty, or invalid Expert Core source or version
- **WHEN** a covered model request is prepared
- **THEN** instruction composition SHALL fail before the external model call
- **AND** the existing execution path SHALL handle the failure without changing its public error contract

### Requirement: Expose version without changing public or persistent contracts
The active Expert Core version SHALL be emitted in internal execution diagnostics for covered model requests. The version MUST NOT require a new public response field, database column, migration, queue, worker, or durable job, and existing public request and response contracts SHALL remain compatible.

#### Scenario: Covered request is diagnosed
- **GIVEN** a covered standalone marketing-agent model request
- **WHEN** its effective instructions are prepared or sent
- **THEN** internal diagnostics SHALL include the active Expert Core version
- **AND** diagnostics SHALL NOT include the full instruction text or user secrets

#### Scenario: Existing client executes a task
- **GIVEN** a client using an existing task, deprecated direct-agent, chat, image, brand-profile, or Telegram contract
- **WHEN** Expert Core foundation is deployed
- **THEN** the public request and response schema SHALL remain compatible
- **AND** no database migration SHALL be required
