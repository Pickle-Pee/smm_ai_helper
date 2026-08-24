# Prompt governance

## Sources and ownership

- Expert Core has one versioned runtime resource for shared non-negotiable reasoning rules.
- `docs/product/marketing-orchestrator.md` is the Orchestrator product contract.
- `docs/product/prompts/orchestrator-production.md` is approved product source material, not a deterministic-foundation runtime prompt.
- `app/module_registry/v1.0.0.json` owns runtime module descriptors, aliases and authority boundaries.
- Specialized module prompts own task-specific expertise only.

A rule is written once under its owner. Shared reasoning belongs to Core; planning/workflow rules to Orchestrator; capability metadata to Registry; expert methods to modules.

## Deterministic Orchestrator foundation

For `add-marketing-orchestrator-foundation`, executable planning behavior is typed code plus explicit OpenSpec scenarios and invariants. The foundation must not load `orchestrator-production.md`, copy it into Python, create `app/prompts/orchestrator` or call an LLM. Product source and typed code are not described as two canonical runtime prompts.

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

For deterministic work with no runtime prompt, prompt version/token review is recorded as not applicable rather than fabricated.

## Review checklist

- No duplicated rule or second routing layer.
- Product source is not labeled runtime unless runtime loads it.
- User context is not embedded in static prompts; dynamic facts are not timeless truth.
- Hidden chain-of-thought is not requested or exposed.
- Simple requests are not forced into a complex response template.
- No guaranteed marketing result.
- Deterministic planner tests prove zero model/prompt calls.
- Rollback path exists.
