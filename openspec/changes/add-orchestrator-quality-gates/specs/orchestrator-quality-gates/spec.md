## ADDED Requirements

### Requirement: Module result gate

The system SHALL validate normalized module results before they are accepted for downstream use.

#### Scenario: Accept complete result

- **WHEN** a result satisfies its declared output contract and has no material unresolved limitation
- **THEN** the gate returns `PASS`

#### Scenario: Accept limited result

- **WHEN** a result is useful but contains a material evidence or coverage limitation
- **THEN** the gate returns `PASS_WITH_LIMITATIONS`
- **AND** the limitation remains attached to downstream context

#### Scenario: Reject unusable result

- **WHEN** a result does not satisfy required output contract fields
- **THEN** the gate returns `FAIL`

#### Scenario: Block for missing dependency

- **WHEN** the module cannot execute because a blocking input or capability is unavailable
- **THEN** the gate returns `BLOCKED`

### Requirement: Evidence and confidence propagation

The system SHALL preserve claim type, evidence provenance, confidence and limitations through downstream handoffs.

#### Scenario: Repeated claim

- **WHEN** a downstream module repeats an upstream claim without new evidence
- **THEN** the claim confidence does not increase solely because of repetition

#### Scenario: New supporting evidence

- **WHEN** new independent evidence supports an upstream claim
- **THEN** confidence may change according to explicit rules
- **AND** the new evidence is recorded

### Requirement: Contradiction handling

The system SHALL represent material evidence conflicts explicitly and SHALL NOT silently average conflicting claims.

#### Scenario: Conflicting periods

- **WHEN** two findings differ because they cover different periods
- **THEN** the conflict record preserves both periods
- **AND** synthesis does not present them as one averaged fact

#### Scenario: User data conflicts with benchmark

- **WHEN** current first-party data conflicts with a generic benchmark
- **THEN** synthesis prioritizes the first-party context for the business decision
- **AND** retains the benchmark as an external reference with its limitation

### Requirement: Dynamic replanning

The orchestrator SHALL reevaluate the highest-value next step after a material accepted finding.

#### Scenario: Root cause changes plan

- **WHEN** an accepted finding shows that the originally planned creative step cannot address the likely bottleneck
- **THEN** the orchestrator produces a revised validated plan or stops with a recommendation
- **AND** it does not execute the original plan mechanically

### Requirement: Stop conditions

The orchestrator SHALL stop when the requested scope is complete, sufficient evidence exists, additional information has diminishing decision value, a tool/data limit is reached or a reversible test is more valuable than more analysis.

#### Scenario: Sufficient answer

- **WHEN** accepted results are sufficient for the requested decision
- **THEN** no additional module is invoked solely for completeness

### Requirement: User-facing synthesis

The system SHALL synthesize accepted module results into one user-facing response appropriate to request complexity.

#### Scenario: Complex response

- **WHEN** multiple accepted module results contribute to the answer
- **THEN** the user receives one prioritized synthesis containing relevant evidence, actions, validation and material risks
- **AND** does not receive a raw list of internal module outputs

#### Scenario: Simple response

- **WHEN** the request is simple
- **THEN** the response is direct
- **AND** the complex response template is not applied mechanically

### Requirement: Deterministic scope

Quality gates SHALL NOT claim to deterministically verify factual truth, causal validity, ethics or arbitrary strategic quality of model-generated content.

#### Scenario: Semantic uncertainty

- **WHEN** a claim is structurally valid but its truth cannot be established by deterministic checks
- **THEN** the gate preserves its evidence, claim type and confidence
- **AND** does not mark it true solely because the contract is complete

