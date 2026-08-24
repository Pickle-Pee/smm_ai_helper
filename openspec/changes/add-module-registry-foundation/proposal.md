## Why

The product defines fifteen marketing modules, while the current runtime has a separate execution registry for five standalone agents. The foundation must establish canonical typed metadata without conflating product module IDs with executable agent IDs or changing current routing.

## What Changes

- Add a read-only product/domain `ModuleRegistry` for immutable descriptors and normalized alias lookup.
- Make `app/module_registry/v1.0.0.json` the single canonical runtime descriptor resource; Python provides loading, validation, and lookup only.
- Define distinct availability and result-status concepts, internal activation/return contracts, authority limits, handoffs, tool capabilities, and optional execution bindings.
- Validate the fixed v1.0.0 module set, aliases, descriptors, handoffs, capabilities, immutability, and optional bindings deterministically and fail fast.
- Preserve `AgentRegistry` as the only mapping from executable IDs (`strategy`, `content`, `analytics`, `promo`, `trends`) to agent classes.
- Add durable verification planning for the initial import from approved source material.

## Capabilities

### New Capabilities

- `module-registry`: Versioned, immutable product module metadata with deterministic validation and read-only lookup.

### Modified Capabilities

None.

## Impact

- Runtime implementation is limited to app-owned registry domain models, the v1.0.0 JSON resource, a loader/provider, and deterministic tests.
- The current Docker `COPY . .` deployment includes `app/module_registry/v1.0.0.json`; no separate Python wheel/sdist packaging configuration exists.
- No public API, database, Alembic, Redis, queue/worker, Telegram, LLM-call, QC-call, routing, `AgentRunner`, or `TaskPipelineService` behavior changes.
- No current agent exactly implements a product module contract, so v1.0.0 declares no execution bindings.

## Out of scope

- Selecting or executing product modules, Marketing Orchestrator behavior, workflows, and LLM-based routing.
- Implementing any of the fifteen expert modules or adapting current agents.
- Public DTO/result-format changes, persistence changes, and unrelated refactoring.
