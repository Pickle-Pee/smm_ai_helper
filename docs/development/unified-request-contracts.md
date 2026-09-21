# Unified request contracts — non-executable foundation

`app/marketing_copilot/` is an internal library for future routing across Chat / Tasks / Marketing Workflow. No existing ingress imports it. There is no default provider, executor dispatch, database access, authorization lookup, URL fetch or worker publication. The existing fixed Telegram MVP remains executable through its own workflow; this foundation does not replace it or connect the generic Orchestrator to execution.

## Boundaries and contracts

1. `MarketingIntentInterpreter` accepts text and an explicitly injected async model callback. The callback receives one instruction, the text and the strict JSON schema and must return a JSON string. There are no provider credentials/default call or retries. Invalid input/output raises `CopilotContractError`; provider exceptions propagate. A future interface must handle those errors without executing anything.
2. `ContextResolver` accepts caller-authorized facts from explicit source layers and returns the existing `PlanningContext`. It neither interprets model text as context authority nor loads BrandProfile/artifacts/conversations itself.
3. `ExecutionPolicy` deterministically selects a proposal from semantic intent and resolved context. It uses exact enum kinds, fixed tool/scenario keys and read-only Registry identities. Free prose, URLs and model-supplied executor names cannot create bindings.
4. `OrchestratorAdapter` creates the unchanged `RequestInterpretation` plus `PlanningContext` for module/workflow proposals only. It does not call the planner or any executor.

`MarketingIntent` is frozen and strict, rejects unknown fields/coercive strings and contains:

- semantic `kind`, `requested_output`, `decision_goal`, optional `business_goal`, and `subject`;
- explicit `external_evidence_required`, `deterministic_calculation_required`, and `ambiguous` booleans;
- at most 16 provided URLs, 16 source references, 16 constraints;
- finite numeric confidence from 0 to 1.

Text fields are nonblank and limited to 2000 characters; references to 2048. Request text is limited to 12000 characters and model output to 32768. JSON duplicate fields, unknown enums, code fences, non-finite constants and extra fields such as `reasoning`, `chain_of_thought`, `executor`, `module_id`, `job_type` or `authorized` fail validation. References must appear literally in the input; syntax validation is not ownership, evidence verification, DNS resolution or SSRF clearance. Future actual fetching must still use UrlAnalyzer's existing security boundary.

`ExecutionDecision` retains the intent and permits exactly these selector combinations:

| Mode | Required selector | Other selectors |
| --- | --- | --- |
| CONVERSATION | none | prohibited |
| DIRECT_TOOL | tool_key | prohibited |
| SINGLE_MODULE | module_id | prohibited |
| WORKFLOW | scenario_key | prohibited |

Missing, mixed or invalid selectors fail during construction. `reason_codes` contains 1–4 unique closed-enum codes; there is no free-form reasoning trace. A decision is not authorization and does not establish executor availability. Registry `1.0.0` remains metadata-only, with fifteen descriptors and zero execution bindings.

## Deterministic v1 policy

Ambiguous/unsupported intent and confidence below 0.7 choose conversation/clarification, without selectors. Only a lead/funnel calculation can currently carry the deterministic-calculation requirement; combined calculation/research or calculation/other-work requests fall back safely. The actual calculator is not implemented or registered by this change.

| Semantic intent | Proposal |
| --- | --- |
| Lead/funnel calculation, calculation required, no external research | DIRECT_TOOL / lead_funnel_calculator_v1 |
| Post generation | SINGLE_MODULE / CREATOR |
| Text editing | SINGLE_MODULE / COPY_EDITOR |
| Competitor analysis | SINGLE_MODULE / COMPETITOR_ANALYSIS |
| Positioning/USP from sufficient existing context | SINGLE_MODULE / POSITIONING |
| Comparative positioning requiring multiple analyses | WORKFLOW / competitive_positioning_v1 |
| Marketing strategy | WORKFLOW / strategy_builder_v1 |
| Conversation, ambiguous/unsupported or insufficient context | CONVERSATION |

For standalone positioning, sufficient means nonempty authorized facts for `product`, `target_or_target_hypothesis`, `customer_job_or_need`, `relevant_alternative`, and `product_truth`, with POSITIONING or explicit_single_module_v1 relevance. Labels, unrelated/unauthorized facts and upstream artifact contents do not satisfy those keys. This is structural completeness, not proof of marketing truth. Missing keys or an explicit need for new external evidence choose conversation/clarification; explicitly comparative work chooses the workflow instead. Other module requests remain preliminary selections; future execution must check their inputs and access separately. External-evidence requirements remain visible in reason codes and adapter constraints.

The generic planner supports explicit_single_module_v1, new_positioning_v1 and competitive_positioning_v1, always PLANNING_ONLY. The comparative proposal selects the bounded competitor-analysis -> positioning scenario; only an explicit external caller may compile it through the separate internal graph runtime. Adapting strategy_builder_v1 produces a valid request with one scenario selector, but the unchanged planner returns UNSUPPORTED, no nodes, and PLANNING_ONLY. It does not make a strategy workflow executable.

## Context precedence and provenance

Each `ContextEntry` is a conflict key around an existing immutable `AuthorizedContextFact`. For typed inputs, `semantic_key` must equal `PlanningInputKey.value`; untyped facts need an explicit stable semantic key. Labels never imply equivalence. Each source layer is a tuple of at most 128 entries; duplicate semantic keys within one layer fail rather than using incidental order.

Precedence: current_request > project_run > brand_profile > conversation. Unauthorized candidates cannot win. An explicit empty/null high-priority value masks stale lower-priority data and is omitted from planning inputs, so the existing planner cannot count it as known. Zero and false remain values. Source tagging adds `CURRENT_REQUEST:`, `PROJECT_RUN:`, `BRAND_PROFILE:` or `CONVERSATION:` before the original source reference; the original fact ID, evidence, confidence, sensitivity and relevance tags are retained. No broader module/scenario relevance is invented. Current/project winners enter project_context; BrandProfile/conversation winners enter known_facts. The caller's inputs and durable profile are never mutated.

Saved artifacts enter only `authorized_upstream_findings` as existing `UpstreamFinding` records. `artifact_reference()` creates an upstream reference for a caller-authorized artifact, not a business fact or lookup. Duplicate (producer_node_id, key) identities fail. The caller owns both fact and artifact authorization before invoking the resolver; UpstreamFinding has no authorization field and the foundation does not infer ownership from a supplied ID. These records are not merged into BrandProfile facts. Existing planner dependency scoping remains unchanged: upstream findings enter only declared dependent packets.

The adapter preserves resolved facts/upstream data, tools, assumptions and constraints. Missing business_goal maps to the explicit `UNSPECIFIED` sentinel with an accompanying assumption because the existing RequestInterpretation requires a nonempty string. Both module and scenario selectors are never set together. Conversation/direct-tool adaptation raises CopilotContractError rather than inventing a selector. Unresolved URLs/source references remain in decision.intent; only a static unresolved-reference constraint is added to planning, with no promotion to authorized evidence or arbitrary constraint text.

## Compatibility and verification

Out of scope and unchanged: public DTOs/routes, Telegram handlers, ChatService, TaskPipelineService, MarketingWorkflowService, Job lifecycle, JobExecution, workers, Redis, delivery, database schema/migrations, Module Registry bindings and the existing planner. No unified runtime integration, arbitrary module execution, generic strategy execution, replanning, synthesis or production deployment is claimed.

Unit tests in `tests/test_marketing_copilot.py` cover selectors/strict fields, injected model parsing and rejection, the policy cases and safe fallbacks, context precedence/provenance, artifact isolation, immutable caller inputs, the adapter and actual existing planner behavior. They also assert zero ingress imports and no calls to provider/agent/QC/URL boundaries. Existing Orchestrator/Registry tests remain part of the focused suite. Live natural-language classification quality, provider integration and end-user routing are not evaluated by model doubles and require a later reviewed integration.

Run from the repository root:

```bash
python -m pytest tests/test_marketing_copilot.py tests/test_marketing_orchestrator.py tests/test_module_registry.py
python -m pytest
python -m compileall app bot
git diff --check
```

Use the two explicitly disposable PostgreSQL databases and optional Redis environment from README for infrastructure tests. No new migration is required. Test results and the final SHA are recorded in the PR/task delivery report.

Local verification on 2026-09-15 (Python 3.12.14, disposable PostgreSQL 15.19): focused suite **265 passed, 0 failed, 0 skipped**; full suite **815 passed, 0 failed, 1 skipped** in 27.28 seconds. The skip is the real Redis test because REDIS_TEST_URL was not set locally. `python -m compileall app bot` and `git diff --check` passed. An explicit diff comparison confirmed the existing services, public interfaces, planner, Registry, workflow/worker, bot and migrations are unchanged. No live model/Telegram calls or new migration commands were required for this foundation; database integration fixtures still exercised their existing migration checks as part of the full suite.
