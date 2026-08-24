## Why

The existing standalone marketing agents each carry their own prompt rules, but the system has no shared reasoning policy that consistently protects evidence quality, calibrated uncertainty, business relevance, customer reality, causality, currentness, ethics, feasibility, risk awareness, testability, and explainability. Establishing EXPERT CORE now gives the current agents and future specialized marketing modules one governed foundation without turning the task pipeline into a new orchestration system.

## What Changes

- Add one canonical, explicitly versioned Markdown runtime resource at `app/prompts/expert_core/v1.0.0.md`, faithfully imported from the archival `agents_prompts/1. EXPERT CORE PRODUCTION.docx` material.
- Treat the DOCX files and `docs/product/prompts/expert-core-production.md` as archival provenance only, and `docs/product/expert-core.md` as the product contract; none of them is a runtime prompt source.
- Add one deterministic composition boundary that produces the effective model instructions from Expert Core and a specialized module's existing instructions.
- Define instruction precedence so non-negotiable Expert Core safety and evidence rules cannot be weakened by module prompts, while modules retain authority over non-conflicting task methods and presentation.
- Apply the shared composition boundary to all marketing-oriented standalone agents currently registered in `AgentRegistry`: `strategy`, `content`, `analytics`, `promo`, and `trends`.
- Preserve each agent's task-specific prompt, structured-output contract, presenter, and public result format.
- Prevent Expert Core from being injected more than once into any individual model request, including repeated or nested use of the composition boundary.
- Expose the active Expert Core version through internal execution diagnostics without adding an API field or database column.
- Add deterministic coverage for composition content and order, versioning, registry coverage, and duplicate prevention.
- Add deterministic initial-import fidelity coverage for the exact ordered section titles 1–59, the `NEVER` and `ALWAYS` non-negotiable groups, and an optional recorded normalized-content checksum.
- Document ownership and the version-bump/review rules for future Expert Core policy changes.
- Record prompt size, composition, and token-impact verification durably in `docs/development/expert-core-verification.md`.

In scope is instruction policy and composition for existing standalone marketing-agent generation calls. Future specialized agents will be expected to use the same boundary when they join the standalone-agent architecture.

Out of scope are public API changes, database models or migrations, Redis, queues, workers, Jobs or other job infrastructure, marketing workflow behavior, competitor/creative/mentor workflows, changes to `TaskPipelineService` responsibilities, changes to chat/image/classifier/clarification/QC prompts, an additional model-based QC call, a universal response schema, and unrelated refactoring. This change also does not introduce a deterministic claim that code can verify the factual truth or strategic quality of arbitrary model output.

## Capabilities

### New Capabilities

- `expert-core`: Defines the canonical versioned Expert Core policy, deterministic instruction composition and precedence, covered standalone marketing agents, duplicate prevention, version observability, and policy governance.

### Modified Capabilities

None. Existing task, chat, image, brand-profile, URL-analysis, and Telegram public contracts remain unchanged.

## Impact

- **Runtime areas:** the shared prompt/instruction layer and the common standalone-agent model-request boundary; existing agent registry and internal logging/diagnostics are reused.
- **Agents:** `strategy`, `content`, `analytics`, `promo`, and `trends` receive Expert Core on each of their generation requests while keeping their current module prompts and result schemas.
- **Public APIs:** no request or response contract changes for `/tasks`, deprecated `/agents`, `/chat`, `/images`, `/brand-profile`, or Telegram.
- **Persistence:** no schema changes, migrations, or new durable state.
- **External integrations:** no new dependency or OpenAI call; covered requests carry a larger input instruction payload, so input-token cost and context usage increase and must be measured during implementation.
- **Rollout:** additive code rollout with prompt-behavior impact only; rollback restores the previous shared agent instruction construction without data rollback.
