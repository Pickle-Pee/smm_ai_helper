# Design: Marketing orchestrator foundation

## Responsibility and lifecycle

The foundation has one responsibility:

```text
typed request interpretation -> minimal validated plan
```

Its planning-only lifecycle is:

```text
INTERPRET -> CHECK_CONTEXT -> CHECK_EVIDENCE -> PLAN
-> VALIDATE_PLAN -> RETURN_PLAN_OR_BLOCK
```

`INTERPRET` validates a structured value supplied by a future authorized caller; it does not parse arbitrary user text. The component does not intercept API or Telegram traffic, replace `TaskRouter` or `AgentRunner`, alter `TaskPipelineService`, instantiate modules, call agents/models/QC, execute or persist a plan, create workflow records, enqueue work, synthesize an answer, replan from runtime findings or learn. Early dispatcher material is design history absorbed into this boundary; no separate runtime dispatcher is created.

## Immutable internal contracts

All collections are deeply immutable and all contracts remain internal. Caller-visible fact and upstream-finding values use a recursive JSON-like value domain only: `None`, booleans, integers, finite floats, strings, tuples, and immutable string-keyed mappings. Lists and mappings are copied recursively; sets, non-string mapping keys, non-finite floats, byte arrays, custom mutable objects, and other non-canonical values are rejected.

### RequestInterpretation

- `requested_output`, `decision_goal`, `business_goal`, `intent`, `object`, `depth`, `mode` and `constraints`;
- exactly one structured selector: `requested_module` (canonical ID or alias) or `scenario_key`.

The foundation validates these fields and rejects absent, ambiguous or unsupported selectors. It never guesses a selector from free text.

### PlanningContext and tagged facts

A future caller supplies already-authorized structured context. Each immutable fact has a stable, explicit, lowercase `fact_id` (`^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$`), a human-only `label`, an optional exact `PlanningInputKey`, value, typed provenance/evidence, finite confidence in `[0.0, 1.0]`, and explicit relevance tags containing canonical module IDs and/or supported scenario keys. Fact IDs are unique across a `PlanningContext`. Labels, IDs, source prose and Registry prose are never normalized into input keys. Optional project fields use the same tagging model. Upstream findings are separately keyed by producer node.

Every planning dataclass validates at construction and raises `InvalidContextValueError` for invalid caller data. Only exact built-in `list`/`tuple` sequence containers, exact built-in `dict` JSON mappings, and exact built-in `set`/`frozenset` semantic-set containers are accepted where their field contracts allow them. A validated exact dictionary is copied into a mapping proxy as an internal immutable output, but every mapping proxy supplied as input is rejected from its outer type before the wrapped mapping is accessed. Container and scalar subclasses and custom mapping/sequence/set implementations are rejected before iteration or method access. Supported sequences are copied into tuples, semantic enum collections into frozensets, and JSON-like values recursively into immutable deterministic containers; bare strings used as sequences, byte arrays, sets in JSON values, mutable/custom metadata, invalid enums, booleans used as confidence, and non-finite/out-of-range confidence are rejected before planning. Fact `source` is optional: `None` means unspecified provenance, while a supplied source must be a non-empty exact built-in string. Source remains descriptive metadata and is excluded from input matching and plan identity.

The planner does not query `BrandProfile`, conversation memory, URL services or artifact persistence and does not accept a raw conversation dump. It includes a fact only when its tags match the current node or scenario, excludes secrets unless explicitly authorized and tagged, and never copies unrelated history.

### OrchestrationPlan

- deterministic `plan_id`, derived from canonical serialization of the validated interpretation, relevant tagged-context identities, Registry version/checksum and scenario key;
- `scenario_key`, nodes and graph dependencies;
- `structural_validity`;
- `data_sufficiency`: `SUFFICIENT`, `PARTIAL` or `INSUFFICIENT`;
- `planning_status`: `VALIDATED`, `BLOCKED`, `UNSUPPORTED` or `INVALID`;
- `execution_readiness`: `PLANNING_ONLY` for Registry `1.0.0`;
- blocking questions, assumptions, limitations and planning-time stop condition.

No random ID is used. A blocked plan can still have a deterministic identity and structurally valid graph.

### PlanNode

- stable scenario-defined `node_id` and canonical Registry module ID;
- objective, scoped inputs, expected outputs and quality gate;
- dependency references and conditional next-step metadata;
- parallelization group/eligibility metadata and immutable context packet.

Aliases are resolved before return. Expected outputs and quality gates are descriptor-backed subsets; scenario rules do not copy entire descriptors.

### Dependencies and inputs

`GraphDependency` represents only a directed execution-order edge. Input requirements use a separate `REQUIRED`, `BLOCKING`, `PREFERRED` or `OPTIONAL` classification. Each machine-readable requirement declares a stable `PlanningInputKey`, priority, applicable scenario and module, and an approved deterministic question template. Registry descriptor prose, including `blocking_for_strong_conclusion`, is never normalized into an identifier or question. The two dependency concepts are never overloaded into one enum.

### ContextPacket

The packet contains relevant project context, known facts, upstream findings, evidence, assumptions, confidence, constraints, available tools and open questions. Only dependent nodes receive findings of their declared upstream nodes. Known blocking inputs are satisfied only by an authorized relevant fact carrying the exact matching `PlanningInputKey`; no string normalization or parsing occurs. Missing preferred/optional inputs create limitations rather than blockers.

## Deterministic scenario catalog

The catalog contains routing rules and graph templates only; descriptors remain owned by Registry `1.0.0`.

### `explicit_single_module_v1`

- Selector: canonical module ID or approved Registry alias.
- Required modules: the one resolved canonical module; edges and parallel groups: none.
- Expected outputs/quality gate: descriptor-backed subsets declared by the structured request, defaulting to descriptor declarations.
- Input requirements: only explicitly supplied typed requirements may be evaluated. This foundation supplies none for the generic single-module case and never derives them from descriptor prose.
- Result: one-node planning-only preliminary plan with explicit limitations, or unknown-module rejection. Descriptor outputs such as `market size` are never treated as missing source inputs.

### `new_positioning_v1`

This scenario is supported by the approved `NEW POSITIONING` workflow, the product source's parallelization example, Registry handoffs from both analyses to `POSITIONING`, and the roadmap.

- Required modules/stable node order: `MARKET_ANALYSIS` (`market_analysis`), `COMPETITOR_ANALYSIS` (`competitor_analysis`), `POSITIONING` (`positioning`).
- Edges: `market_analysis -> positioning` and `competitor_analysis -> positioning`.
- Expected outputs: `market_analysis` selects `market_definition`, `segments`, `audience_findings`, `market_opportunities`, `research_gaps.`; `competitor_analysis` selects `competitor_set`, `observable_positioning`, `offers`, `proof`, `patterns`, `market_gaps`, `differentiation_hypotheses.`; `positioning` selects `category`, `target`, `value_proposition`, `differentiation`, `RTB`, `positioning_statement`, `USP_directions`, `offer`, `message_hierarchy`, `claim_risks`, `validation_plan.`. The trailing periods are part of those three canonical Registry `1.0.0` output strings. Every name is validated as a member of the current descriptor; the catalog does not redefine its schema.
- Required/blocking inputs: product/category and materially relevant geography; competitor name/URL or category plus search scope; product, target hypothesis, customer need and relevant alternative. Known tagged context is checked first. Upstream findings may support downstream evidence but cannot fabricate product truth or target.
- Preferred/optional inputs: descriptor declarations; absence limits confidence/coverage but does not block a preliminary plan.
- Parallel group `evidence_analysis`: `market_analysis` and `competitor_analysis` only. `positioning` is sequential after both.
- Stop/block: block only for a missing decision-changing required/blocking input after context checking; otherwise return the validated planning-only graph.

Any other scenario key returns `UNSUPPORTED` with `UNSUPPORTED_SCENARIO`; no graph is guessed. Catalog expansion requires an OpenSpec revision.

## Graph invariants and ordering

Catalog node order is stable. Dependencies sort by downstream then upstream stable node ID. Topological order uses Kahn's algorithm with catalog order as tie-breaker. Questions deduplicate by input key and order by earliest affected node, input declaration order and normalized text.

Validation requires unique node IDs; canonical registered module IDs; no aliases; existing dependency targets; no self-dependencies or cycles; deterministic topological ordering; no node parallel with a direct/transitive dependency; descriptor-compatible outputs and quality gates; explicit blocking inputs; no more than three unique decision-changing questions; no question for known inputs; optional/preferred absence as limitations; unsupported-scenario rejection; and structural validity reported separately from execution readiness.

For `new_positioning_v1`, validation compares independently declared exact node IDs, node-to-module mapping, edge set, dependency references, parallel membership, and node/edge order. Both `market_analysis -> positioning` and `competitor_analysis -> positioning` are mandatory; missing or extra edges are invalid even when the module sequence is correct.

The same independent catalog fixes conditional transition metadata as: `market_analysis -> (positioning, BLOCKING_INPUT_MISSING)`, `competitor_analysis -> (positioning, BLOCKING_INPUT_MISSING)`, and `positioning -> (None, BLOCKING_INPUT_MISSING)`, where each pair is `(next_if_pass, next_if_fail)`. Validation compares both fields exactly for every canonical node; these values describe planning metadata only and do not enable execution.

## Sufficiency, readiness and stop conditions

Structural validity describes graph soundness. Data sufficiency describes authorized input coverage. Planning status describes return/block/rejection. Execution readiness describes whether modules can run. Registry `1.0.0` has zero bindings, so every valid plan is `PLANNING_ONLY`; module existence never implies executability.

- `PLAN_COMPLETE`: supported, structurally valid and no missing blocking planning input.
- `BLOCKING_INPUT_MISSING`: decision-changing required/blocking input remains after context matching; return at most three questions.
- `UNKNOWN_MODULE`: explicit module/alias resolution fails.
- `UNSUPPORTED_SCENARIO`: key is outside the catalog.
- `INVALID_PLAN`: graph or descriptor invariant fails.

Execution completion, runtime quality validation, dynamic replanning, synthesis, delivery and learning belong to future changes.

### Plan-state consistency matrix

Every row remains `PLANNING_ONLY`; any combination not listed raises `InvalidPlanError` rather than returning an `INVALID` plan.

| Structural validity | Planning status | Data sufficiency | Questions | Limitations | Stop condition | Meaning |
| --- | --- | --- | --- | --- | --- | --- |
| `VALID` | `VALIDATED` | `SUFFICIENT` | none | optional | `PLAN_COMPLETE` | complete planning input |
| `VALID` | `VALIDATED` | `PARTIAL` | none | required | `PLAN_COMPLETE` | preliminary plan with explicit limitations |
| `VALID` | `BLOCKED` | `INSUFFICIENT` | 1-3 unique approved questions | optional | `BLOCKING_INPUT_MISSING` | decision-changing input is absent |
| `INVALID` | `UNSUPPORTED` | `INSUFFICIENT` | none | required | `UNSUPPORTED_SCENARIO` | no supported graph is returned |

Global readiness, zero-binding, question-bound, uniqueness, and state-consistency checks run before unsupported-result early return. A blocked plan without evidence, an executable unsupported result, a ready plan with questions, partial data without limitations, sufficient data with a missing-input stop, or any contradictory status/stop/sufficiency combination is invalid.

## Scoped deterministic plan identity

Plan identity is computed only after authorization, relevance filtering, alias resolution, and graph construction. Its canonical payload contains the typed interpretation, scenario, canonical graph identity, Registry version/fingerprint, and the immutable facts or upstream findings that actually survived into selected node packets. It excludes unauthorized facts, facts for unselected modules, unrelated conversation content, irrelevant upstream findings, and caller collection ordering. Effective relevant value changes alter identity; irrelevant additions do not.

## Architecture, source and rollback

Standalone requests continue through the current single-task pipeline. Future execution is owned by `MarketingWorkflowService` after durable Job/workers exist. This foundation does not use `MarketingWorkflowPersistenceService`, `MarketingRun` or `MarketingArtifact`.

The deterministic implementation loads no Orchestrator prompt. Behavior is typed code plus these approved rules. Removing it requires no migration and leaves current runtime flows intact.
