## Purpose

Defines a deterministic internal boundary that validates immutable normalized module results and derives safe downstream decisions without executing work or judging semantic truth.

## ADDED Requirements

### Requirement: Exact normalized contracts

The system SHALL accept only the exact enums, fields, optionality, defaults, scalar/container types and prefixed ASCII IDs defined by the design, including `bat_` batch identity, SHALL reuse Registry `ModuleId` and `ModuleResultStatus`, and SHALL deeply freeze accepted caller data. It SHALL derive the canonical batch SHA-256 fingerprint and carry batch ID/fingerprint on every output.

#### Scenario: Exact immutable construction
- **WHEN** an exact normalized evaluation batch is constructed and caller containers later mutate
- **THEN** the batch remains unchanged and all output ordering is deterministic

#### Scenario: Unsupported input
- **WHEN** input contains a subclass, custom collection, caller mapping proxy, wrong-prefix/duplicate ID, unsupported object or unresolved reference
- **THEN** it raises `QualityGateContractError` before evaluation

### Requirement: Closed contract error boundary

The system SHALL validate untrusted types before access and SHALL normalize caller-caused supported Python and Registry lookup errors to `QualityGateContractError` without catching system exits or unrelated programmer defects.

#### Scenario: Hostile collection
- **WHEN** a hostile custom collection is supplied
- **THEN** it is rejected without iteration, lookup, hashing, comparison, formatting, copying, `str()` or `repr()`

#### Scenario: Expected lookup failure
- **WHEN** a caller supplies an unknown module or handoff
- **THEN** the expected Registry error is exposed only as `QualityGateContractError`

### Requirement: Deterministic time semantics

The system SHALL accept only exact aware `datetime` values, normalize them to UTC preserving microseconds, serialize with `Z`, and SHALL use no ambient clock, timezone, filesystem or environment time.

#### Scenario: Freshness comparison
- **WHEN** both evidence timestamps are present
- **THEN** normalized instants derive `NEWER`, `OLDER` or `SAME`
- **AND** either absent timestamp derives `UNKNOWN`

#### Scenario: Invalid timestamp
- **WHEN** a timestamp is naive, a subclass or a string
- **THEN** construction raises `QualityGateContractError`

### Requirement: Registry-supported validation only

The system SHALL use injected Registry `1.0.0` only for canonical module identity, exact declared-output membership and registered descriptor handoffs, and SHALL require zero execution bindings.

#### Scenario: Unsupported module schema inference
- **WHEN** a result names a registered output
- **THEN** membership may be validated
- **AND** the gate does not infer invocation-specific required outputs or semantic authority from Registry prose

### Requirement: Derived legal gate state

Callers SHALL supply module status but SHALL NOT supply structural validity, gate outcome, execution readiness or synthesis eligibility. The system SHALL derive them using the exhaustive design matrix and SHALL return only `PLANNING_ONLY` readiness.

#### Scenario: Pass
- **WHEN** a `PASS` result has at least one usable claim, `SUFFICIENT` evidence, no material limitation/reasons and permitted authority
- **THEN** the derived outcome is `PASS`

#### Scenario: Pass with limitations
- **WHEN** a `PASS_WITH_LIMITATIONS` result has a usable claim, `SUFFICIENT` or `LIMITED` evidence and a material limitation without failure/blocking reasons
- **THEN** the derived outcome is `PASS_WITH_LIMITATIONS`

#### Scenario: Fail
- **WHEN** a structurally valid `FAIL` result has no accepted claim, typed failure reasons, no blocker and `INSUFFICIENT` or `NOT_ASSESSED` evidence
- **THEN** the derived outcome is `FAIL` and synthesis eligibility is `INELIGIBLE`

#### Scenario: Blocked
- **WHEN** a `BLOCKED` result has no claim, typed blocking reasons, no failure and `NOT_ASSESSED` evidence
- **THEN** the derived outcome is `BLOCKED` and synthesis eligibility is `INELIGIBLE`

#### Scenario: Illegal combination
- **WHEN** any status/evidence/claim/materiality/reason/authority combination is outside the design matrix
- **THEN** deterministic first-error precedence raises `QualityGateContractError`

### Requirement: Identity-based conservative propagation

The system SHALL propagate only through resolved explicit lineage IDs, union provenance/assumptions/limitations by ID, reject conflicting identities, and emit stable lexical ordering without text similarity.

#### Scenario: Confidence ceiling
- **WHEN** a repeated, reformulated or derived claim references parents
- **THEN** its canonical enum confidence does not exceed the most conservative parent under `UNKNOWN < LOW < MEDIUM < HIGH`
- **AND** any `UNKNOWN` parent makes the ceiling `UNKNOWN`

#### Scenario: New evidence
- **WHEN** new evidence is attached
- **THEN** it is preserved with provenance
- **AND** confidence does not increase in this foundation

### Requirement: Exact contradiction evaluation

The system SHALL compare contradictions only through exact object, segment, period and metric-definition keys and caller-selected evidence belonging to each claim, preserve both claims, never choose or aggregate evidence, never average/delete values and never present precedence as truth.

#### Scenario: Incomparable claims
- **WHEN** any comparison key differs
- **THEN** state is `INCOMPARABLE` and both claims remain

#### Scenario: First-party precedence
- **WHEN** comparison keys match, source classes are first-party versus generic benchmark, both timestamps exist and first-party is equal or newer
- **THEN** state is `PRIORITIZED` with `FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK`
- **AND** both claims remain

#### Scenario: Uncovered precedence
- **WHEN** timestamps are missing, first-party is older, classes tie or no exact rule applies
- **THEN** state is `UNRESOLVED`

### Requirement: Unresolved contradiction eligibility

Unresolved/incomparable claims SHALL remain in evaluated results but SHALL be excluded from unqualified accepted claim IDs with typed exclusions.

#### Scenario: Some usable claims remain
- **WHEN** at least one claim remains eligible after contradiction handling
- **THEN** the final accepted outcome is `PASS_WITH_LIMITATIONS`
- **AND** a material `UNRESOLVED_CONTRADICTION` limitation is preserved

#### Scenario: No usable claim remains
- **WHEN** every claim is excluded by unresolved/incomparable contradictions
- **THEN** final outcome is `FAIL` with `NO_USABLE_CLAIMS`

### Requirement: Gate-compatible decisions

The system SHALL validate triggers after final gate derivation and SHALL enforce the complete gate × decision matrix and accepted-gate precedence defined by the design.

#### Scenario: Blocked gate
- **WHEN** final gate is `BLOCKED`
- **THEN** decision is `BLOCKED` with matching blockers
- **AND** stop/replan triggers are illegal

#### Scenario: Failed gate
- **WHEN** final gate is `FAIL`
- **THEN** decision is `STOP` with `RESULT_FAILED`
- **AND** blocking/replan triggers are illegal

#### Scenario: Stop and replan triggers coexist
- **WHEN** an accepted gate has both top-tier completion/sufficient-evidence and replan triggers
- **THEN** `STOP` wins
- **AND** duplicate triggers do not change the result

#### Scenario: Replan beats lower stop
- **WHEN** an accepted gate has replan triggers and only diminishing/tool/capability stop triggers
- **THEN** decision is `REPLAN_REQUIRED`

### Requirement: Immutable synthesis eligibility manifest

The system SHALL derive the exact batch-identified manifest fields, deterministic contradiction limitations and exhaustive `RESULT_FAILED`, `RESULT_BLOCKED` or `UNRESOLVED_CONTRADICTION` exclusions defined by the design. Equal derived preimages SHALL deduplicate and different-preimage ID collisions SHALL raise `QualityGateContractError`.

#### Scenario: Stable batch and derived identity
- **WHEN** equal normalized batches and contradiction adjustments are evaluated
- **THEN** their batch fingerprints, derived limitation IDs and exclusion IDs are identical
- **AND** changing any contract-relevant batch value changes the fingerprint preimage

#### Scenario: Mixed outcomes
- **WHEN** accepted, failed, blocked and unresolved results are evaluated together
- **THEN** only eligible accepted identities appear in accepted lists
- **AND** every excluded identity has a typed resolved exclusion

#### Scenario: No synthesis behavior
- **WHEN** a manifest is created
- **THEN** it contains no generated prose, raw module dump, hidden reasoning or public response wrapper

### Requirement: Pure internal architecture

The foundation SHALL live only under `app/marketing_orchestrator/quality_gates/`, remain deterministic/idempotent/side-effect-free and make zero agent, presenter, router, QC, OpenAI, persistence, context, Job, Redis, queue, worker or workflow calls.

#### Scenario: Existing runtime compatibility
- **WHEN** the foundation is implemented
- **THEN** existing planner/validator, agents, presenters, public DTOs, `AgentRegistry`, `QCService` and `TaskPipelineService` remain unchanged
- **AND** no public API, Telegram behavior, migration or transaction ownership is added
