# Copilot business goal consistency

Baseline: `cd980fa8cacaf6bc1ae52027c0d3e2199cf6568d` (`master` after PR #120).
This correction changes only `OrchestratorAdapter` and its regression coverage.

## Execution path and authority

`POST /copilot/execute -> CopilotAPIService.execute -> MarketingCopilotService.execute
-> merge_projected_context -> ContextResolver -> ExecutionPolicy -> OrchestratorAdapter
-> MarketingOrchestratorPlanner -> PlanCompiler -> GraphExecutionService`.

The API loads owner-scoped BrandProfile context and explicit current fields. It
loads or saves a validated `InterpretedRequest` for the owner, request key and exact
message fingerprint before application execution. On replay the application still
merges that immutable interpretation with the current authorized caller inputs;
loading an interpretation does not assign new source roles or permissions.

| Boundary | Existing business-goal contract |
| --- | --- |
| Semantic intent | Optional nonblank `MarketingIntent.business_goal`; absence is null. An intent goal has precedence in `RequestInterpretation`. `decision_goal` remains the requested decision/work objective and is never converted. |
| Provider projection | Nullable fixed `business_goal` slot, a literal contiguous excerpt of at most 4000 characters. Validated excerpts convert to the existing internal facts-array representation. Neither provider object grants authority. |
| Projected request facts | Server-owned `http_context.entry` assigns canonical `PlanningInputKey.BUSINESS_GOAL`, authorization, relevance, sensitivity and source. The excerpt remains an unverified user assertion. This existing conversion permits consumption of that exact goal value; the adapter does no semantic completion or paraphrasing. |
| Explicit current request | Presence in `context.model_fields_set` is retained by `exclude_unset=True`. Explicit entries mask projection even when null, empty or unauthorized. Duplicate explicit semantic keys remain errors. |
| Brand context | Existing `brand_entries` maps bounded strings and the existing `goals` list to a business-goal string. It remains lower-priority durable brand context. No profile is mutated. |
| Resolved PlanningContext | `ContextResolver` selects by semantic key: CURRENT_REQUEST > OWNED_SITE > PROJECT_RUN > BRAND_PROFILE > CONVERSATION. Only authorized entries can win. An authorized empty winner masks lower layers and is omitted. Unauthorized presence masks projection but cannot win resolution; an authorized lower layer can still win. Facts retain their ID, evidence, confidence, sensitivity and relevance, with source-layer prefixes. |
| Persisted interpretation | PostgreSQL stores the internal `InterpretedRequest` (semantic intent plus projected facts), not the adapter's legacy `RequestInterpretation`. Hydration revalidates literal grounding and strict fields. Null intent goals and historical facts arrays remain valid and unchanged. |

`ContextResolver` owns layer precedence; the adapter consumes its resolved result,
without re-reading raw text, reconstructing omitted masks, looking up artifacts or
ranking source-prefix strings. Upstream findings remain dependency-scoped findings,
not candidate business goals. Owned-site claim objects remain descriptive claims;
they are not flattened into goal strings.

## Adapter correction

An existing intent goal remains first. When it is null, the adapter carries a
nonblank string from a resolved fact with the exact typed BUSINESS_GOAL input key,
a source, authorization, non-SECRET sensitivity and eligible relevance:

- Single module: relevance to the selected module or `explicit_single_module_v1`.
- Workflow: relevance to the selected scenario. For `strategy_builder_v1`, an
  explicitly VIRTUAL_CMO-scoped goal is also eligible because VIRTUAL_CMO is the
  existing required business-goal consumer.

The original fact and all its provenance remain in the same context collection.
No facts, broader relevance tags or evidence are synthesized. An intent/context
conflict retains the intent value in `RequestInterpretation` and the resolver's
winning fact in context, preserving the existing meanings of both layers.

Without an eligible goal the adapter keeps the existing `UNSPECIFIED` sentinel
and missing-goal assumption. With an eligible goal it does not append that
assumption. Existing caller assumptions are preserved, including any historical
assumption text; the adapter does not rewrite them.

Canonical untyped labels alone are not promoted: ContextEntry explicitly separates
semantic keys from labels, and the semantic conflict key is not retained in
PlanningContext for untyped facts. The strategy planner's existing legacy label
handling stays unchanged. Numeric, boolean, list and object values remain context
values but cannot be coerced into the legacy string business goal.

## Compatibility

No public DTO, provider schema/prompt, persisted schema, migration, resolver,
planner, compiler, Quality Gate, confirmation rule or POSITIONING behavior changes.
Existing compiled plans and accepted artifacts are restored through their existing
codecs, without adaptation or replanning. Their IDs and stored assumptions are not
rewritten. Newly planned requests with a context goal can have a different plan ID
because the interpretation and missing-goal assumption are now consistent; stable
run identity and the existing conflict checks remain unchanged. A replay of an
already-started run must continue to use its stored plan rather than replace it.

Regression tests cover intent and resolved-layer goals, conflicts, presence masks,
authorization, sensitivity, relevance, literal excerpt preservation, absent goals,
legacy interpretation hydration and compiled-plan round trips. Application tests
inject a saved interpretation and assert deterministic compilation across reordered
explicit entries, preserving context provenance with zero interpreter/executor
provider calls.

## Verification

Verification on 2026-10-13 with Python 3.12.14, disposable loopback PostgreSQL
15.19 and Redis 8.10.2, with external providers disabled:

- Focused adapter/interpretation/strategy/planner/compiler suite: **623 passed**.
- `python -m pytest -q --tb=short`: **3453 passed, zero failures or skips**.
- `python -m compileall -q app bot` and `git diff --check`: passed.
- Independent final code review: no unresolved material findings.

The 48 new regression cases are in `tests/test_copilot_business_goal.py`. The first
full run encountered four Redis connection failures because the local test service
had exited at startup. After correcting its launch and verifying readiness, the
strategy integration rerun and complete suite passed without implementation changes.
Existing deprecation warnings remain. No production access, real provider calls,
merge or deployment were performed; no migration was added.
