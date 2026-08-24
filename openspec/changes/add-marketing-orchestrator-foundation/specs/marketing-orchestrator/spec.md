## ADDED Requirements

### Requirement: Typed interpretation boundary

The foundation SHALL validate an internal structured interpretation containing requested output, decision goal, business goal, intent, object, depth, mode, constraints and exactly one explicit module/alias or supported scenario selector, and SHALL NOT infer arbitrary free text or connect to user-facing routers.

#### Scenario: Preserve distinct goals

- **WHEN** a caller supplies requested output, decision goal and business goal
- **THEN** all three remain distinct immutable fields

#### Scenario: Reject unstructured request

- **WHEN** no structured module or scenario selector is supplied
- **THEN** interpretation fails instead of guessing from text

### Requirement: Exact scenario catalog

The deterministic catalog SHALL contain exactly `explicit_single_module_v1` and `new_positioning_v1` in this foundation.

#### Scenario: Explicit module

- **WHEN** a canonical module ID or approved alias is selected
- **THEN** the system returns a one-node planning graph using the canonical ID

#### Scenario: New positioning

- **WHEN** `new_positioning_v1` is selected
- **THEN** `MARKET_ANALYSIS` and `COMPETITOR_ANALYSIS` are independent parallelizable upstream nodes
- **AND** `POSITIONING` sequentially depends on both
- **AND** each node's selected handoff outputs and quality gate are validated against its Registry descriptor

#### Scenario: Unsupported scenario

- **WHEN** any other scenario key is supplied
- **THEN** the result is explicitly unsupported and no guessed graph is returned

### Requirement: Immutable planning contracts

The foundation SHALL return immutable internal plan, node, dependency, input-requirement and context-packet contracts with deterministic identities and ordering.

#### Scenario: Stable identity and order

- **WHEN** equivalent interpretations and tagged context are planned against the same Registry version/checksum
- **THEN** plan ID, node order, dependency order and topological order are identical
- **AND** no random ID is required

#### Scenario: Separate dependency concepts

- **WHEN** a node depends on an upstream node and also requires an input
- **THEN** the graph edge and the `REQUIRED`/`BLOCKING`/`PREFERRED`/`OPTIONAL` input classification are represented separately

### Requirement: Deterministic context scoping

The foundation SHALL accept only already-authorized structured facts with explicit module/scenario relevance metadata and SHALL NOT query BrandProfile, conversation, URL or artifact services.

#### Scenario: Include relevant known context

- **WHEN** an authorized fact is tagged for a node or selected scenario
- **THEN** it may enter that node's packet and satisfies a matching input before questions are generated

#### Scenario: Exclude unrelated or secret context

- **WHEN** a fact lacks matching relevance or explicit secret authorization
- **THEN** it is excluded from the packet

#### Scenario: Scope upstream findings

- **WHEN** an upstream finding exists
- **THEN** it is included only in packets for nodes declaring that upstream dependency

#### Scenario: Optional input absent

- **WHEN** a preferred or optional input is missing
- **THEN** the plan records a limitation and is not blocked solely for that absence

### Requirement: Graph and descriptor validation

The foundation SHALL validate unique node IDs, canonical registered modules, resolved aliases, dependency targets, self-edges, cycles, deterministic topology, parallel metadata, descriptor-compatible outputs and quality gates, and explicit blocking inputs before returning a plan.

#### Scenario: Invalid dependency structure

- **WHEN** a dependency target is missing, a self-edge exists or a cycle exists
- **THEN** plan validation returns `INVALID_PLAN`

#### Scenario: Invalid parallel metadata

- **WHEN** a node is marked parallel with a direct or transitive dependency
- **THEN** plan validation returns `INVALID_PLAN`

#### Scenario: Descriptor mismatch

- **WHEN** an expected output or quality-gate item is absent from the module descriptor
- **THEN** plan validation returns `INVALID_PLAN`

### Requirement: Bounded blocking questions

The foundation SHALL ask at most three unique questions, each mapped to a missing decision-changing required/blocking input after known context is checked.

#### Scenario: Known input

- **WHEN** tagged context already contains an input
- **THEN** no blocking question asks for it again

#### Scenario: More than three gaps

- **WHEN** more than three decision-changing inputs are missing
- **THEN** deterministic ordering selects at most the first three unique questions

### Requirement: Separate validity, sufficiency, status and readiness

The plan SHALL separately represent structural validity, `SUFFICIENT`/`PARTIAL`/`INSUFFICIENT` data sufficiency, planning status and execution readiness.

#### Scenario: Metadata-only modules

- **WHEN** a graph is structurally valid against Module Registry `1.0.0`
- **THEN** its execution readiness is `PLANNING_ONLY`
- **AND** registered module existence is not treated as an execution binding

### Requirement: Planning-only lifecycle and isolation

The foundation SHALL end at `RETURN_PLAN_OR_BLOCK` and SHALL make zero module, agent, model, QC, database, Redis, worker or persistence calls.

#### Scenario: Existing standalone request

- **WHEN** an existing standalone request is processed
- **THEN** it continues through the unchanged `TaskRouter`, `AgentRunner` and `TaskPipelineService` path

#### Scenario: Plan returned

- **WHEN** planning returns `PLAN_COMPLETE` or `BLOCKING_INPUT_MISSING`
- **THEN** no execution, runtime validation, replanning, synthesis, delivery or learning begins

### Requirement: Source governance

The deterministic foundation SHALL use typed code and rules approved by this OpenSpec as its runtime planning source and SHALL NOT load or copy the product Orchestrator source material as a runtime prompt.

#### Scenario: Foundation initialization

- **WHEN** the deterministic planner is initialized
- **THEN** no Orchestrator prompt resource is loaded and no LLM call is made
- **AND** no `app/prompts/orchestrator` resource is required
