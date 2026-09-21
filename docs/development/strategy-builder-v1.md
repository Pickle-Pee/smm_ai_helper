# Internal Strategy Builder v1

`MARKETING_STRATEGY -> strategy_builder_v1 -> PlanCompiler -> GraphExecutionService`
is explicitly composed by the production Copilot API using Registry 1.2.0. `MarketingCopilotService` returns
`WORKFLOW_STARTED` after durable start; it neither executes nodes nor waits for
completion. The production `ModuleGraphWorker` lane executes the graph. Telegram
starts and discovers runs through the HTTP API and renders accepted artifacts;
there is no separate graph Telegram delivery queue or additional synthesis call.

## Composition and authority

Pass `registry_version="1.2.0"` to `build_marketing_copilot_service`. The factory
loads exactly `ModuleRegistry.load("1.2.0")`, composes six executors and a matching
compiler. `url_analyzer` supplies competitor fetching; `market_analyzer` supplies
market fetching. Both are explicitly injected safe UrlAnalyzer capabilities.
The graph service must share the same executor registry. The default remains
1.1.0, with three executors; there is no automatic upgrade or fallback.

Planning still uses metadata Registry 1.0.0 and returns `PLANNING_ONLY`.
`strategy_builder_v1` is independently authorized in runtime-owned immutable
`EXECUTABLE_SCENARIOS`. Planning support, binding presence and execution permission
remain separate. `new_positioning_v1` remains unauthorized for execution.

## Inputs and scoping

Before durable start, caller-authorized first-party context must supply
`business_goal`, `product`, `target_or_target_hypothesis`, `customer_job_or_need`,
`relevant_alternative`, and `product_truth`. These may come from current text,
project context or BrandProfile through the existing ContextResolver precedence.
An explicitly interpreted business goal can supply the goal; `UNSPECIFIED`
cannot. Empty, unauthorized and SECRET facts do not satisfy strategy requirements.
All missing required keys are returned in **one** grouped `NEEDS_INPUT`, including
all six when necessary. The three-question cap remains for earlier scenarios.

Use existing `AuthorizedContextFact` / `ContextEntry` contracts. Tag shared
strategy facts with `scenario_relevance=frozenset({"strategy_builder_v1"})`, or
explicitly authorize each consuming module with `module_relevance`. Data scoped
only to one module is not silently shared with others. Required product context
must be available to POSITIONING and the goal/product to VIRTUAL_CMO.

Research uses explicit untyped fact labels:

- `competitor_urls`: a list of HTTP/HTTPS fetch targets, at most three unique URLs.
- `market_sources`: the existing market executor source records, with
  `source_reference`, `source_class` (EXTERNAL_PRIMARY/EXTERNAL_SECONDARY), `excerpt`.
- `market_source_urls`: up to three explicit source URLs, requiring authorized
  SITE_FETCH and an injected safe analyzer.
- Existing market/customer fact slots `existing_customers`, `internal_sales_data`,
  `current_segments`, `research`, `customer_findings` can also enable market analysis.

MARKET_ANALYSIS receives its explicit research and authorized business context.
If needed, `product` is mapped to `product_or_category` without changing its value
or first-party provenance. No market node is created from a broad strategy request
alone. Missing research creates coverage limitations, not clarification blockers.

Competitor lists accept at most 128 raw entries (including duplicates); each URL
is bounded to 2048 characters. Credentials, non-HTTP(S), invalid ports, whitespace,
control characters and backslashes are rejected. Canonicalization lowercases
scheme/IDNA host, removes default ports and fragments, supplies `/` for an empty
path, preserves path/query semantics, deduplicates, then sorts. Node IDs follow
that sorted order. Repeats and host-case/default-port variants do not change plan
identity. Planning does no DNS or network I/O; safe fetching remains executor-owned.
Each competitor ContextPacket contains exactly its own normalized source, not
the entire competitor list or market-source list.

Raw `MarketingIntent.provided_urls` does not assign source roles. URL order has
no own-site/competitor meaning. An own website alone cannot supply product truth
or satisfy the minimum first-party inputs. There is no own-site diagnostic,
BUSINESS_DIAGNOSTICS binding, pseudo-module or autonomous market/web search.

## Fixed bounded graph

```text
optional market_analysis --------------------\
optional competitor_analysis_1 ---------------\
optional competitor_analysis_2 ----------------> positioning -> virtual_cmo -> experiments
optional competitor_analysis_3 ---------------/
```

Create only the supplied research branches: zero to three competitors and zero
or one market analysis. With no research the graph is exactly
`positioning -> virtual_cmo -> experiments`. The maximum is seven nodes.
Research jobs are created together; independent workers may execute their provider
calls concurrently, outside transactions. There is no free-form graph generation,
arbitrary module selection, recursive research or replanning.

## Immutable execution policy and persistence

Existing `compiled_execution_plan.v1` dataclasses, strict JSON field sets and
fingerprint algorithm remain unchanged. Old Registry 1.1/1.2 v1 plans remain
executable and retain their identity. There is no silent conversion.

Strategy uses `compiled_execution_plan.v2`: each node adds a `failure_mode`, each
dependency has a `mode`, and the plan persists bounded planning limitation codes.
These fields participate in the fingerprint. The compiler and persisted reader
revalidate the exact bounded topology, Registry version and policy:

| Node/edge | Policy |
|---|---|
| MARKET_ANALYSIS, each COMPETITOR_ANALYSIS | OPTIONAL |
| POSITIONING, VIRTUAL_CMO | REQUIRED |
| EXPERIMENTS | OPTIONAL |
| Research -> POSITIONING | OPTIONAL_CONTRIBUTOR |
| POSITIONING -> VIRTUAL_CMO -> EXPERIMENTS | HARD |

A HARD dependency requires an accepted artifact. OPTIONAL_CONTRIBUTOR waits for
the upstream terminal outcome: accepted artifact or canonical FAILED Job.
POSITIONING cannot overtake a slow/running/retrying research branch. Failed optional
branches never become fake results. Accepted optional branches are normal upstream
results. Full accepted ancestor closure is restored for downstream Quality Gates:
VIRTUAL_CMO receives only market/competitor/positioning ancestors; MARKET_ANALYSIS
is a root with no upstream results. EXPERIMENTS receives the strategy and its
accepted ancestor lineage. Partial claim acceptance cannot release any payload.

Run locks serialize Job creation/advance; artifact acceptance, Job completion and
dependent scheduling commit together. Existing lease fencing, bounded retries and
DB due scans are preserved. PostgreSQL terminal Job states reconstruct optional
outcomes after restart; state_json is a summary, not a scheduling authority.
Redis remains a best-effort wakeup; claim-time exhaustion can advance the graph
for recovery through the DB due scan even without a wakeup.

## Outcomes and limitations

An optional BLOCKED, quality rejection, terminal provider/output failure or
exhausted attempt remains `JobStatus.FAILED`. No JobStatus is added. A required
BLOCKED still blocks the run; other required terminal failures fail it. Downstream
work is not scheduled; previously accepted research artifacts remain persisted.

All required nodes accepted plus at least one failed optional node yields terminal
`completed_with_limitations`. In particular, failed EXPERIMENTS cannot invalidate
an accepted VIRTUAL_CMO strategy. Successful terminal runs have `run.error=None`.
If every scheduled node succeeds, the run is `completed`, even when planning
limitations record absent market/competitor evidence or economics.

Bounded `state_json` uses `evidence_coverage.v1`: safe limitation codes, optional
node IDs and allowlisted failure reasons, accepted node IDs, and supplied/accepted
competitor counts. It includes `market_research_not_supplied`,
`competitor_research_not_supplied`, `economics_unavailable`, `optional_node_failed`,
and `only_one_competitor_analyzed` when applicable. Raw provider exception text
and BLOCKED payload details are never persisted as limitations.

Before execution, coverage is serialized into the existing ContextPacket
`open_questions`, explicitly marked as limitations, not factual claims. This
keeps it visible to VIRTUAL_CMO without turning it into first-party evidence or
resource constraints. The persisted compiled ContextPacket is never mutated.

## Results and verification

The strategy artifact is the existing **VIRTUAL_CMO ModuleExecutionResult**.
EXPERIMENTS is a separate downstream artifact. Research and positioning remain
reusable module artifacts. No extra fixed strategy schema or LLM synthesis is
introduced: VIRTUAL_CMO is the synthesis expert; planning/scheduling belong to
the planner and runtime. A later presentation layer may assemble a bundle.

Actor/request ID replay preserves the same durable run for the same compiled
plan; a changed plan under the same identity conflicts.

`tests/test_strategy_builder.py` covers bounds, normalization, grouped inputs,
source-role isolation, explicit composition, policy tampering and codecs.
`tests/test_strategy_builder_postgresql.py` exercises A-F using real executors,
dispatcher/gates and PostgreSQL with fake sources/models; optional failures,
parallel provider calls, barriers, concurrent advance, stale claims, separate
process recovery, Redis failure and idempotency. Existing graph tests cover old
1.1/1.2 runs; the frozen 1.1 fixture was produced by the original compiler at
`d84d3169a9481b6173556762d8cb6f3b04823fb6`, and runs after process recreation.

No migration is needed: policies live in versioned plan JSON, summary in state_json,
and MarketingRun.status already accepts the new string. No old migration changes.
No live paid providers are used by tests. Safe internal manual verification is to
compose Registry 1.2 with fake capabilities, submit complete typed context, inspect
initial research Jobs, and drive ModuleGraphWorker until terminal status.

Quality Gates verifies structural provenance and acceptance, not semantic truth.
This bounded scenario does not deliver, publish, execute campaigns, search the web,
infer own-site roles, or start follow-up conversations.

### Executed verification (2026-09-18)

Base: merged PR #60, `d84d3169a9481b6173556762d8cb6f3b04823fb6`.
Windows / Python 3.12.14, disposable PostgreSQL 15 and Redis 7, fake providers:

- Focused planner/compiler/graph/Copilot/Registry/module/Quality Gates/fixed
  workflow/standalone suites: **955 passed**. Final additional topology and
  corruption regressions are included in the full run below.
- `python -m pytest tests/test_strategy_builder.py -q --tb=short`: **32 passed**.
- `python -m pytest -q --tb=short`: **1287 passed, zero skips**.
- `python -m compileall app bot`: passed.
- `git diff --check`: passed.
- `python -m alembic check`: no new upgrade operations detected.

The pytest PostgreSQL fixtures executed `alembic upgrade head` before integration
checks. Existing deprecation warnings remain. Diff review covered versioned
persistence, execution authorization, source scoping, complete claim acceptance,
terminal barriers, lock/fencing behavior and unchanged production boundaries.
