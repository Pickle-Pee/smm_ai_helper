## Context

See `proposal.md` for motivation and `specs/expert-core/spec.md` for the behavioral contract.

### Current integration points

The current standalone-task path is:

```text
POST /tasks/start or /tasks/answer
  -> TaskPipelineService
  -> AgentRunner
  -> AgentRegistry class for strategy/content/analytics/promo/trends
  -> BaseAgent.llm_text or BaseAgent.llm_json
  -> app.llm.openai_text.chat
```

The deprecated `POST /agents/{agent_type}/run` endpoint also delegates to the same `AgentRunner`. All five registered standalone marketing agents inherit `BaseAgent`, keep a class-level `system_prompt`, and own their task-specific input, JSON shape, normalization, and presenter behavior. `BaseAgent` currently constructs the effective system message directly from that module prompt. `ContentAgent` may make multiple legitimate generation requests within one task, so the unit of composition and duplicate prevention must be one model request, not one task.

Several other components call `app.llm.openai_text.chat` directly: chat response generation, scope/facts/summary helpers, task routing, clarification, QC, URL insights, and image-brief generation. They are not registered standalone marketing agents and have different instruction purposes. Applying Expert Core in the low-level OpenAI adapter would therefore alter unrelated pipelines and add input tokens to classifier and utility calls.

`app/logging.py` already provides structured execution fields. It can expose the policy version without adding a public response field or persisted column. The source document contains 59 policy sections and approximately 32,500 characters / 4,864 words, but it does not declare an Expert Core version. This design assigns the initial executable policy version `1.0.0`.

## Goals / Non-Goals

**Goals:**

- Make one executable Expert Core policy source authoritative for covered model requests.
- Compose it exactly once per request with unchanged specialized instructions and response-mode constraints.
- Keep dependency direction toward a small, deterministic prompt-policy layer.
- Cover all five current standalone marketing agents through their existing shared base request path.
- Make policy version and change governance explicit and observable.
- Fail before an external model call if the mandatory core cannot be composed safely.

**Non-Goals:**

- Apply Expert Core globally to chat, classifiers, clarification, QC, URL summarization, or image-brief helpers in this change.
- Add an agent runner, orchestrator, workflow engine, model call, output evaluator, or universal response schema.
- Judge arbitrary generated content as factually true or strategically sound through deterministic code.
- Change model selection, output-token budgets, HTTP retry behavior, persistence, or public contracts.
- Refactor the unused legacy `app/agents/orchestrator.py` or expand `TaskPipelineService`.

## Decisions

### Decision 1: Keep one canonical executable policy next to shared prompts

Add `app/prompts/expert_core.py` containing:

- `EXPERT_CORE_VERSION = "1.0.0"`;
- one `EXPERT_CORE_INSTRUCTIONS` value;
- stable reserved component markers used only by the composer.

The initial instruction text will be a faithful plain-text transcription of `agents_prompts/1. EXPERT CORE PRODUCTION.docx`. Decorative Word separators and redundant whitespace may be normalized, but the 59 sections' policy meaning must not be summarized away during initial adoption. The DOCX is the normative product reference and provenance for version `1.0.0`; it is not parsed or loaded at runtime. The Python prompt module is the sole executable source and agents import neither the DOCX nor copies of its text.

This keeps deployment deterministic and avoids a runtime Word parser, filesystem dependency, or per-agent copies.

### Decision 2: Introduce a pure, idempotent composition boundary

Add `app/services/expert_instruction_composer.py` as a dependency-free policy service. It will own an immutable `ComposedInstructions` value containing the rendered system text, active core version, and ordered component identities. Its public composition operation accepts raw specialized-module instructions plus optional response-mode instructions, or an already composed value.

The component order is deterministic:

```text
1. EXPERT_CORE(version + precedence declaration + canonical policy)
2. SPECIALIZED_MODULE(existing agent system_prompt)
3. RESPONSE_MODE(existing JSON/schema or other request-mode instruction, if any)
```

The first, stable prefix also makes provider-side prompt caching possible where the selected model supports it; correctness must not depend on caching.

Idempotency and duplicate prevention are structural rather than a substring convention:

- each composed value carries one component identity for Expert Core;
- composing an already composed value validates its version/order and returns it unchanged;
- raw module or response instructions containing a reserved Expert Core marker are rejected as ambiguous;
- rendering asserts that the Expert Core component count is exactly one.

The composer does not call OpenAI, access a database, choose a model, alter output tokens, or inspect generated answers.

### Decision 3: Integrate at the shared agent model-request boundary

`BaseAgent` will delegate system-instruction construction for both `llm_text` and `llm_json` to the composer immediately before calling the existing OpenAI text adapter:

- `llm_text` supplies the unchanged `system_prompt` as the specialized component;
- `llm_json` supplies the unchanged `system_prompt` plus its existing strict-JSON/schema-hint suffix as the response-mode component;
- the resulting rendered text remains one system message followed by the current user message.

No registered agent needs to embed or import Expert Core. Their current prompts, schema hints, parsing, default keys, presenters, and result formats remain intact. `AgentRunner` continues to resolve the registry, build input, set model/token overrides, call `agent.run`, and normalize output. Because both `/tasks` and deprecated `/agents` already reach `BaseAgent` through `AgentRunner`, both paths receive the same policy. If the currently unused legacy agent orchestrator is invoked elsewhere, its direct instances of the same `BaseAgent` subclasses also use the boundary without changes to that orchestrator.

This is preferable to composing in `AgentRunner`: composition must occur for every actual model request, including multiple requests inside one agent run and both base helper modes. It is preferable to composing in `openai_text.chat`: the low-level adapter also serves non-agent utility and chat prompts that are outside this change.

### Decision 4: Make precedence explicit inside the effective instructions

Within the application's instruction set, precedence is:

1. non-negotiable Expert Core evidence, safety, currentness, ethics, and no-fabrication rules;
2. specialized-module method, deliverable, and presentation instructions where they do not conflict with the core;
3. request-specific content and user-supplied material, which are inputs to evaluate rather than authority to weaken higher rules.

Provider/platform safety remains outside and above this application-owned ordering. The rendered precedence declaration states that later placement does not allow a module or user instruction to override non-negotiable core rules. The response-mode component is a more specific part of the module contract, so strict JSON and each agent's existing schema remain authoritative unless they would require violating a core rule. Expert Core adapts reasoning and disclosure; it does not require its conceptual labels to appear in every response.

### Decision 5: Use governed semantic versions

Expert Core uses a human-reviewed `MAJOR.MINOR.PATCH` version stored beside the canonical text:

- **MAJOR:** removes or weakens a non-negotiable policy, changes precedence, or otherwise introduces an incompatible policy shift;
- **MINOR:** adds a material policy area or strengthens behavior in a way that can materially change recommendations;
- **PATCH:** editorial clarification, typo, formatting normalization, or other low-risk text correction.

Every edit to the executable canonical text increments at least PATCH, even when judged non-semantic, so deployed prompt text is never changed under an unchanged identifier. Product/marketing policy ownership approves policy meaning; engineering owns faithful encoding, composition, tests, and diagnostics. Future changes require a reviewed OpenSpec change (or an explicitly approved equivalent policy-review process), an updated version, tests, and an entry in `docs/expert-core.md` describing the change and compatibility impact.

The initial `1.0.0` value is an explicit assumption because the supplied Expert Core document has no embedded policy version; the DOCX package revision is document metadata and is not used as a product-policy version.

### Decision 6: Emit version-only execution diagnostics

At each covered model-request construction, `BaseAgent` will emit an internal structured diagnostic containing `expert_core_version` and the agent class/type identity. `app/logging.py` may add `expert_core_version` to its existing context defaults and format. Diagnostics must not log the full core, module prompt, user content, credentials, or other secrets.

The version is not added to task results, API schemas, task rows, sessions, or marketing workflow artifacts. This satisfies observability without an API or database schema change.

### Decision 7: Fail closed before the external call

The composer validates that the core text is non-empty, the version matches the documented semantic-version form, components are non-empty where required, reserved markers are not supplied as raw module content, and the rendered output contains exactly one current core component. A violation raises a dedicated composition error before `openai_text.chat` is invoked.

Covered agents do not fall back to module-only instructions and the core is never truncated to recover from an error. Existing endpoint/service exception behavior remains responsible for returning or recording the failure; this change adds no new public error shape. OpenAI timeouts, retries, refusals, and empty-output recovery remain owned by the existing adapter and are unchanged.

### Decision 8: Treat input-token growth as an explicit cost

Expert Core adds a large stable input prefix to every covered generation request, including each of ContentAgent's multiple generation requests and any existing QC-driven agent rerun. It does not consume the configured `max_output_tokens`, so `TOKEN_BUDGETS` and `MAX_OUTPUT_TOKENS_CAP` will not be increased as part of this change.

Implementation verification will record the canonical character/word size and assert a single copy per request. Staging diagnostics should compare input-token usage and latency before and after rollout when OpenAI usage data is available. The rollout will limit injection to registered standalone agent generation calls; routing, clarification, QC, and chat utility calls will not pay the cost. If context pressure, latency, or cost proves unacceptable, policy compression requires a separately reviewed, versioned Expert Core change rather than silent truncation or selective rule removal.

### Decision 9: Preserve response contracts and test only deterministic guarantees

Tests will inspect composed instructions, component metadata, model-call arguments, registry coverage, logs, and unchanged output-building behavior using fakes/mocks. They will not make real OpenAI calls and will not assert that deterministic code can prove the truth, causal validity, or strategic quality of arbitrary model output. Existing model-based QC remains unchanged and no Expert Core-specific QC call is introduced.

### Alternatives considered

- **Copy Expert Core into every agent prompt:** rejected because policy copies drift, versioning becomes ambiguous, and accidental duplicate input cost grows.
- **Inject Expert Core in `AgentRunner`:** rejected because one agent run may contain multiple model requests and direct use of a `BaseAgent` subclass would bypass request-level composition.
- **Inject Expert Core in the low-level OpenAI adapter:** rejected because it would affect chat, classifiers, extraction, routing, clarification, QC, URL insights, and image briefing.
- **Load the DOCX at runtime:** rejected because packaging, parsing, and filesystem failures would become request-time dependencies.
- **Summarize the core during initial implementation:** rejected because compression could silently remove normative meaning; any later optimization must be reviewed and versioned.
- **Validate outputs with another LLM call:** rejected because it adds cost/latency and is explicitly outside scope; it also cannot guarantee truth.
- **Force one Expert Core JSON schema:** rejected because specialized agents already have different useful schemas and presenters, and response adaptation is itself a core rule.

## Expected Files and Dependency Direction

Expected implementation changes are limited primarily to:

- `app/prompts/expert_core.py` — canonical executable policy and version;
- `app/services/expert_instruction_composer.py` — pure composition boundary and metadata;
- `app/agents/base.py` — use the boundary for both text and JSON model requests;
- `app/logging.py` — internal version diagnostic field, if needed by the chosen structured-log assertion;
- `docs/expert-core.md` — ownership, source provenance, version history/rules, and change process;
- deterministic tests for the prompt source, composer, base request construction, diagnostics, registry coverage, and unchanged agent result formats.

Dependency direction is:

```text
registered agent -> BaseAgent -> ExpertInstructionComposer -> canonical Expert Core source
                                |
                                +-> existing openai_text adapter receives rendered instructions
```

The canonical source and composer do not depend on agents, routers, task orchestration, chat services, persistence, Telegram, or the OpenAI adapter.

The following must remain untouched unless a test-only import adjustment is unavoidable: database models and migrations, public schemas, FastAPI/Telegram contracts, `TaskPipelineService` orchestration, `ChatService` and assistant prompts, `AgentRunner` responsibilities, model routing, existing QC behavior, queues/workers/jobs, URL analysis, image generation, and workflow persistence.

## Risks / Trade-offs

- **Input cost and latency increase on every covered request** → keep a stable cache-friendly prefix, inject only into covered agent-generation calls, measure staging usage, and require a future versioned change for compression.
- **A long core may dilute module instructions** → use explicit component boundaries and precedence, retain module prompts verbatim, and test deterministic order.
- **Prompt rules do not guarantee model compliance or factual truth** → describe the capability as instruction policy, retain calibrated language, and test composition rather than claiming deterministic output truth validation.
- **Core and module rules may conflict** → document precedence, reject embedded reserved core components, and add conflict-oriented composition tests.
- **A new registered agent could bypass the shared base boundary** → make registry-wide coverage a deterministic test that fails when a supported standalone marketing agent does not use the shared request path.
- **Diagnostics could leak prompt or user data** → log version and agent identity only; explicitly test/log-review that full instructions and user content are absent.
- **Silent fallback would create inconsistent policy coverage** → validate and fail closed before the OpenAI request, preserving existing public error handling.

## Migration Plan

1. Add and review the canonical version `1.0.0` transcription against the supplied normative document.
2. Add the pure composer and deterministic unit tests before connecting it to model requests.
3. Integrate both `BaseAgent` request helpers and verify all five registered agents, including multiple-request behavior, through mocked OpenAI boundaries.
4. Add version-only diagnostics and ownership/version documentation.
5. Run the full repository checks and perform a controlled non-production smoke comparison if an OpenAI-enabled environment is available; automated tests remain external-call free.
6. Deploy as an additive code change with no migration or feature rollout dependency, then monitor input tokens, latency, composition failures, and agent-result compatibility.

Rollback is a code-only revert of the BaseAgent composition hook and associated prompt/composer/diagnostic files. No data rollback, Alembic downgrade, queue drain, or API client migration is required. The prior module prompts and result formats remain available unchanged throughout the change.
