## Context

`AgentRegistry` maps five executable agent IDs to classes and supplies metadata used by `TaskRouter`; `AgentRunner` instantiates those classes and `TaskPipelineService` owns the existing single-task flow. Product documentation separately defines fifteen canonical marketing module IDs. These namespaces overlap conceptually but are not equivalent.

The Dockerfile uses `WORKDIR /app` and `COPY . .`, so `app/module_registry/v1.0.0.json` will be available at `/app/app/module_registry/v1.0.0.json`. The repository has `requirements.txt` but no wheel/sdist packaging configuration; imports run from the copied repository. The implemented Expert Core convention also uses a versioned app-owned resource plus typed loading/validation code.

## Goals / Non-Goals

**Goals:**

- Establish one immutable, read-only product metadata registry.
- Establish a single app-owned canonical runtime source at version `1.0.0`.
- Make optional execution compatibility explicit and safe.
- Fail fast on incomplete, ambiguous, invalid, or mutable registry data.
- Preserve current execution and public contracts.

**Non-Goals:**

- Replacing or extending task routing, agent execution, or the task pipeline.
- Adding an orchestrator, workflow engine, model-based routing, LLM/QC calls, persistence, queues, workers, or Telegram behavior.
- Implementing the fifteen product modules or changing current agent contracts.

## Decisions

### 1. Two registries have disjoint responsibilities

`AgentRegistry` remains the execution registry and source of truth for executable standalone agent IDs and classes. `ModuleRegistry` is a read-only product/domain metadata provider. It returns descriptors and resolves aliases; it never instantiates agents, chooses an execution path, acts as a service locator, or creates a runner/orchestrator.

Future Marketing Orchestrator work may consume `ModuleRegistry` through this read-only boundary. This change does not inject it into `TaskRouter`, `AgentRunner`, or `TaskPipelineService` and does not change their decisions or call counts.

### 2. Canonical resource and source precedence

`app/module_registry/v1.0.0.json` is the single canonical runtime registry. Descriptor data MUST NOT be duplicated in Python constants or Markdown. Python models/loaders provide typed loading, validation, immutable projection, and lookup only.

- `docs/product/prompts/module-registry-production.md`: approved source material for the initial import, not a runtime source.
- Archival DOCX files: source history only; none are currently present in the repository.
- `docs/product/module-registry.md`: product contract, not a descriptor copy.
- `docs/development/module-registry-verification.md`: durable evidence template, not runtime data.

The resource declares `source_version: "1.0.0"`. Initial import verification may record SHA-256 over normalized JSON: UTF-8; object keys sorted lexicographically; array order preserved; no insignificant whitespace. The checksum is evidence, not another descriptor source.

### 3. Domain model

An immutable descriptor contains canonical `module_id`; one or more module types (`PRIMARY`, `SUPPORTING`, `OVERLAY`, `SYNTHESIS`); purpose, applicability, and authority limits; inputs classified as `required`, `preferred`, `optional`, or `blocking_for_strong_conclusion`; outputs, tool flags, quality gates, aliases, and handoffs; `availability_status` (`metadata_only` or `execution_bound`); and an optional execution binding with an existing `agent_id`.

Availability is distinct from internal `ModuleResultStatus` (`PASS`, `PASS_WITH_LIMITATIONS`, `FAIL`, `BLOCKED`). The internal activation contract carries module ID, objective, user goal, required output, relevant context, known facts, upstream findings, evidence, assumptions, confidence, constraints, available tools, and open questions. The internal return contract carries module ID, result status, summary, findings, evidence, assumptions, hypotheses, recommendations, risks, confidence, open questions, strategic issues, and handoff recommendation. Neither contract replaces public DTOs, `AgentInput`, `AgentOutput`, agent result dictionaries, presenters, or task result formats.

### 4. Execution bindings and compatibility

A binding is metadata only. Its target MUST exist in `AgentRegistry`; it grants no execution authority. Only an `exact` compatibility finding permits a binding. `partial` and `none` remain metadata-only. Module aliases never become agent aliases.

| Canonical module ID | Possible agent ID | Classification | Binding allowed | Prompt/run-contract evidence |
| --- | --- | --- | --- | --- |
| `VIRTUAL_CMO` | `strategy` | partial | no | Produces SMM positioning, segments, funnel, channels, content/offers and a 7-day plan; lacks business/economic diagnosis, resource trade-offs, strategic bets, decision triggers, and the registry return contract. |
| `CREATOR` | `content` | partial | no | Produces a content plan and posts; lacks the broader creative-system outputs, gates, authority limits, and registry return contract. |
| `BUSINESS_DIAGNOSTICS` | `analytics` | partial | no | Produces metrics plans, diagnosis, benchmarks and next steps; lacks required business-economics scope and normalized module contract. |
| `AD_AUDIT` / `EXPERIMENTS` | `promo` | partial | no | Combines campaign structure, hypotheses and testing rules but implements neither evidence-led ad diagnosis nor the full experiment-design contract. |
| `TREND_MONITORING` | `trends` | partial | no | Produces trend ideas and an experiment roadmap, but does not require fresh external evidence/provenance and lifecycle fields for current claims. |

All other product modules are `none`. Therefore v1.0.0 has zero execution bindings. A later change may bind only an exact implementation with updated evidence.

### 5. Alias normalization and lookup

Normalization is deterministic:

1. require a string and trim leading/trailing Unicode whitespace;
2. apply Unicode case folding;
3. replace each contiguous run of Unicode whitespace, hyphens (`-`), or underscores (`_`) with one underscore;
4. reject an empty result.

Canonical IDs and aliases share one normalized lookup namespace. Duplicate normalized aliases, aliases colliding with any canonical ID (including their own descriptor), and keys resolving to multiple descriptors are configuration errors. Lookup returns the canonical descriptor and never creates or mutates one. Agent IDs are outside this namespace.

### 6. Deterministic fail-fast validation

Loading v1.0.0 MUST fail before registry use for duplicate, missing, or unexpected canonical IDs; a count other than fifteen; not exactly one descriptor per ID; duplicate/empty/ambiguous aliases; alias/canonical collisions; empty required fields; invalid enums; unsupported tool flags; missing handoff targets; any self-handoff; unknown binding targets; `metadata_only` with a binding; `execution_bound` without a validated exact binding; invalid source version; or attempted mutation.

Supported v1.0.0 tool flags are `web_access`, `file_analysis`, `site_fetch`, `image_generation`, and `code_generation`. Initial-import verification compares every descriptor's IDs, aliases, inputs, outputs, flags, gates, handoffs, authority limits, availability/binding state, source version, and optional checksum with approved source material.

### 7. Implementation boundary

Implementation is limited to a new app-owned module-registry package/resource and focused tests. Routers, Telegram handlers, database/migrations, `AgentRegistry` mappings, `TaskRouter`, `AgentRunner`, `TaskPipelineService`, public schemas, presenters, and agent implementations remain untouched.

## Risks / Trade-offs

- [Future modules appear executable] -> expose `metadata_only` and declare zero v1.0.0 bindings.
- [Markdown and JSON drift] -> JSON alone is runtime-canonical; verification records import evidence.
- [Normalization creates hidden collisions] -> validate one namespace and fail rather than select precedence.
- [Registry becomes an orchestrator] -> keep its API read-only and exclude selection/execution.

## Migration Plan

1. Implement immutable types and loader.
2. Import approved source material once into the v1.0.0 JSON and record evidence.
3. Validate at load/test time and expose lookup without routing integration.
4. Roll back by removing the unused provider/resource; no data/API rollback is needed.

There are no unresolved pre-implementation questions.
