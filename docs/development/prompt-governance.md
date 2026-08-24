# Prompt governance

## Sources and ownership

- `docs/product/prompts/expert-core-production.md` — shared reasoning policy.
- `docs/product/prompts/orchestrator-production.md` — orchestration policy.
- `app/module_registry/v1.0.0.json` — canonical runtime module descriptors, version `1.0.0`.
- `docs/product/prompts/module-registry-production.md` — approved initial-import material, not runtime data.
- Specialized module prompts — task-specific expertise only.

A rule is written once under its owner. Shared reasoning belongs to Core; planning/workflow rules to Orchestrator; capability metadata to Registry; expert methods to modules.

- CORE владеет общими non-negotiable reasoning rules.
- ORCHESTRATOR владеет goal interpretation, planning, routing, quality-gate flow, replanning, synthesis и stopping.
- MODULE REGISTRY владеет read-only descriptors, aliases, internal activation/return contracts и authority limits; current task routing and execution remain outside it.
- Modules владеют domain methods и module-specific outputs.

For `add-marketing-orchestrator-foundation`, executable planning behavior is typed code plus explicit OpenSpec scenarios and invariants. The foundation must not load `orchestrator-production.md`, copy it into Python, create `app/prompts/orchestrator` or call an LLM. Product source and typed code are not described as two canonical runtime prompts.

For `add-orchestrator-quality-gates`, typed contracts and deterministic OpenSpec rules own only normalized-result structural validation, propagation, contradiction records, explicit next-step/stop decisions and synthesis eligibility. The foundation does not make the broader product-source replanning or synthesis prose executable, and it does not add a prompt or model/QC call.

A model-driven planner requires a separate OpenSpec change, exactly one versioned runtime prompt, deterministic contract tests, model evals, and token/call-budget and latency review.

## Change process

1. Identify the rule owner and product rationale.
2. Describe observable/internal contract behavior in OpenSpec.
3. Change the single runtime source, if one exists.
4. Version runtime prompts when applicable.
5. Add deterministic tests and stabilized model evals where applicable.
6. Check conflicts, ordering and duplicate injection.
7. Measure token/call budget and latency for model-driven behavior.
8. Update product docs and roadmap.

For Module Registry changes, descriptor content is edited once in the versioned JSON. Python constants and Markdown must not duplicate descriptors. Import/version evidence belongs in `docs/development/module-registry-verification.md`, optionally with normalized JSON SHA-256.

## Review checklist

## Review checklist

- No duplicated rule or second routing layer.
- Product source is not labeled runtime unless runtime loads it.
- User context is not embedded in static prompts; dynamic facts are not timeless truth.
- Hidden chain-of-thought is not requested or exposed.
- Simple requests are not forced into a complex response template.
- No guaranteed marketing result.
- Deterministic planner tests prove zero model/prompt calls.
- Rollback path exists.
