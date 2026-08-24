## ADDED Requirements

### Requirement: Immutable normalized-result boundary

The system SHALL accept only already-typed caller-supplied normalized module results with stable result/claim/evidence/assumption/limitation IDs, canonical registered module identity, explicit claim types, provenance, assumptions, limitations, finite confidence, optional registered handoffs and `PLANNING_ONLY` execution readiness. Contracts SHALL defensively copy and deeply freeze exact supported built-in scalar and container types and SHALL expose no unrestricted mutable `Any` field.

#### Scenario: Caller mutates source data

- **WHEN** caller-owned containers are changed after normalized contract construction
- **THEN** the constructed value remains unchanged

#### Scenario: Malformed contract

- **WHEN** a value has an unsupported/subclass type, invalid ID, duplicate identity, dangling reference, unknown module, illegal handoff or contradictory state
- **THEN** construction/evaluation raises `QualityGateContractError`
- **AND** does not convert the error into `FAIL` or `BLOCKED`

### Requirement: Separate legal gate states

The system SHALL keep module status, structural validity, gate outcome, evidence sufficiency, confidence, material limitations, contradiction state, next-step decision, stop decision, execution readiness and synthesis eligibility distinct and SHALL enforce the design legal-state matrix.

#### Scenario: Complete success

- **WHEN** a valid `PASS` result has accepted claims, sufficient evidence and no material limitation
- **THEN** the gate outcome is `PASS`

#### Scenario: Useful limited result

- **WHEN** a valid `PASS_WITH_LIMITATIONS` result has usable claims and at least one material limitation
- **THEN** the gate outcome is `PASS_WITH_LIMITATIONS`
- **AND** every material limitation remains attached downstream

#### Scenario: Explicit unusable result

- **WHEN** a structurally complete `FAIL` result has typed failure reasons and no accepted claims
- **THEN** the gate outcome is `FAIL`
- **AND** it is excluded from future synthesis

#### Scenario: Legitimate blocked result

- **WHEN** a structurally complete `BLOCKED` result declares a typed missing blocking input or unavailable capability
- **THEN** the gate outcome is `BLOCKED`
- **AND** missing normalized fields would instead be a contract error

### Requirement: Structural checks do not prove truth

Gate evaluation SHALL be deterministic, idempotent and side-effect-free and SHALL NOT claim factual truth, evidence independence, causality, ethics or strategic quality from contract completeness or arbitrary prose.

#### Scenario: Complete unsupported claim

- **WHEN** a claim is structurally complete but its truth cannot be established structurally
- **THEN** the gate preserves its type, provenance, confidence and limitations
- **AND** does not mark it true

### Requirement: Conservative evidence propagation

The system SHALL preserve stable claim/evidence identities and provenance, assumptions and material limitations. Repetition or reformulation SHALL NOT increase confidence. Because this contract cannot verify evidence independence, attaching new evidence SHALL preserve it but SHALL NOT increase confidence in this foundation.

#### Scenario: Repeated claim

- **WHEN** a downstream packet repeats or reformulates a claim without a new reviewed confidence policy
- **THEN** the stable source identity is retained
- **AND** confidence stays equal or decreases

#### Scenario: Identity collision

- **WHEN** unequal records reuse one stable identity
- **THEN** propagation raises `QualityGateContractError`

### Requirement: Typed contradiction handling

The system SHALL accept contradictions only as typed records or from explicitly comparable typed fields and SHALL preserve object, segment, period, metric definition, provenance, freshness, compared claim IDs, resolution state and any deterministic precedence reason.

#### Scenario: Current first-party versus benchmark

- **WHEN** comparable claims have matching comparison keys, explicitly current first-party evidence and explicitly generic benchmark evidence
- **THEN** deterministic precedence MAY select the first-party claim
- **AND** both claims remain present
- **AND** precedence does not assert semantic truth

#### Scenario: Incomparable or tied claims

- **WHEN** comparison keys differ, freshness is missing, or precedence inputs tie
- **THEN** the contradiction remains unresolved
- **AND** values are not averaged or deleted

### Requirement: Pure replanning and stop decisions

The system SHALL derive only `CONTINUE_CURRENT_PLAN`, `REPLAN_REQUIRED`, `STOP` or `BLOCKED` from explicit typed triggers using the documented precedence. It SHALL NOT infer materiality from prose, mutate plans/findings, generate/execute a revised plan or invoke modules.

#### Scenario: Material finding invalidates dependency

- **WHEN** an accepted material finding or invalidated dependency is explicitly supplied
- **THEN** the decision is `REPLAN_REQUIRED`
- **AND** existing plans and findings remain unchanged

#### Scenario: Sufficient decision evidence

- **WHEN** sufficient decision evidence, diminishing value or reversible-test preference is explicitly supplied and no higher-precedence blocker/failure exists
- **THEN** the decision is `STOP` with its typed reason
- **AND** stopping does not mean execution occurred

### Requirement: Synthesis eligibility is not synthesis

The system MAY return an immutable deterministic manifest listing accepted result/claim IDs, material limitations, unresolved contradictions and excluded results with typed reasons. It SHALL NOT generate user-facing prose, raw module dumps, hidden chain-of-thought or a mandatory public response wrapper.

#### Scenario: Limited accepted and failed results

- **WHEN** a limited accepted result and a failed result are evaluated together
- **THEN** the manifest includes eligible accepted identities and their material limitations
- **AND** excludes the failed result with a typed reason

### Requirement: Architectural isolation

The foundation SHALL make zero LLM or `QCService` calls, SHALL NOT execute agents/modules, query or write persistence/context, create Jobs, use Redis/queues/workers, modify `TaskPipelineService`, APIs, Telegram, agents or presenters, and SHALL preserve Registry `1.0.0` with zero bindings and all plans as `PLANNING_ONLY`.

#### Scenario: Gate evaluation

- **WHEN** any legal normalized result is evaluated
- **THEN** no external or mutable runtime boundary is called
- **AND** existing runtime contracts remain unchanged

