# Internal unified Copilot execution

`MarketingCopilotService` is an application coordinator, not another marketing agent.
Import it explicitly from `app.marketing_copilot.service`; compose providers with
`build_marketing_copilot_service` in `app.marketing_copilot.factory`. Existing package
exports remain a pure semantic foundation. The production HTTP Copilot adapter uses
this service; Telegram calls that API. Worker-main executes the resulting persisted
Jobs independently. Existing chat, standalone task and fixed MVP APIs are retained.

## Contracts and caller responsibilities

`CopilotRequest` is a frozen, validated internal value containing positive internal
`actor_id`, bounded `request_id`, message, optional project/run identity, four tuples
of existing `ContextEntry` facts, explicit `UpstreamFinding` references, authorized
tool capabilities, assumptions/constraints and optional strict `FunnelInput`.
No ORM entity, FastAPI Request or Telegram object crosses this boundary.

The caller authorizes the actor, each fact, project/run and artifact reference, and
SITE_FETCH capability. There is no persistence-backed context retrieval here.
`ContextResolver` preserves explicit request > project/run > BrandProfile > conversation,
including explicit empty masks. The legacy executor `competitor_url` slot is canonicalized
to `competitor_or_category_scope` before resolving precedence, so an old profile URL
cannot override a literal current URL. Duplicate aliases fail closed. The interpreter
checks that extracted URLs occur literally in the request. One URL may become a
fetch-target fact; it is never represented as collected evidence.

Artifacts stay upstream findings scoped by existing planner dependency rules. There is
no broad user-artifact retrieval, reference hydration, or automatic attachment of saved
results to synchronous modules. Callers must supply relevant business facts for this
first fast path; simply naming a saved artifact does not supply its facts or claims.

`CopilotExecutionResult` validates the exact kind/payload and decision-mode match:

| Kind | Payload |
| --- | --- |
| CONVERSATION | `conversation_delegate=True` |
| DIRECT_RESULT | strict `FunnelOutput` |
| MODULE_RESULT | existing `ModuleExecutionResult` |
| WORKFLOW_STARTED | `WorkflowStarted(run_id, plan_id, status="durably_started")` |
| NEEDS_INPUT | one `Clarification(code, alternatives, blocking_reasons)` |

`alternatives` is a tuple of alternative required-field groups: all keys in one group
are needed, any complete group can resolve the question. Presentation/localization is
a future ingress concern. Unsupported/ambiguous intents do not become general chat
success. A genuine conversation returns a delegate instruction for existing chat code.
The result includes a deterministic actor/request execution identity.

## Deterministic tools

`app.marketing_tools` imports no module executor, persistence, model or network stack.
An explicit registry resolves only `lead_funnel_calculator_v1`. `FunnelInput` uses strict
Decimals and an explicit target; `conversion_rate_percent=5` means 5%, not 0.05%.

| Supplied inputs | Formula / output |
| --- | --- |
| budget, CPC, conversion rate | clicks = budget / CPC; leads = clicks × rate / 100 |
| traffic, conversion rate | leads = traffic × rate / 100 |
| budget, CPL | leads = budget / CPL |
| required leads, conversion rate | required traffic = required leads / (rate / 100) |
| required leads, CPL | required budget = required leads × CPL |

Amounts/counts are finite in [0, 10^15]; input precision is at most 12 decimal places.
Unit costs are in [10^-12, 10^15], rates in [0, 100]. Inverse traffic requires a
strictly positive rate. Outputs above 10^15 fail validation. No inferred costs,
defaults, range truncation, currency conversion or guessed rates are allowed.
Extra parameters also require clarification, since overlapping formulas may conflict.
Calculations use 34 significant decimal digits. Explicit output assumptions describe
constant supplied rates/costs, common currency without fees and fractional expected
counts; no rounding to whole people is implied.

Prefer typed `calculation=FunnelInput(...)` from trusted callers. A deliberately small
full-message Russian grammar also recognizes these exact forms (case insensitive,
decimal point or comma):

```text
Рассчитай лиды при бюджете 100000, CPC 50 и конверсии 5%
Рассчитай лиды при бюджете 100000 и CPL 1000
Рассчитай лиды при трафике 2000 и конверсии 5%
```

Other wording, ranges, currencies or missing parameters require structured input.
The semantic interpreter may make its one injected intent call; after selecting
DIRECT there are no further model calls, including clarification or arithmetic.

## Fast module path

```text
interpret -> ContextResolver -> ExecutionPolicy.SINGLE_MODULE
-> OrchestratorAdapter -> planner ContextPacket
-> ModuleExecutionRequest -> shared ModuleExecutorDispatcher
-> QualityGateEvaluator -> MODULE_RESULT or NEEDS_INPUT
```

Only the three bound Registry 1.1.0 modules run. CREATOR v1 needs scoped product,
audience, message/product truth and `asset_format=text_post`; it generates no images.
COMPETITOR_ANALYSIS uses the injected existing safe site analyzer capability and
requires an explicit URL plus SITE_FETCH. POSITIONING runs alone when the existing
policy finds sufficient positioning facts; it does not initiate research.
Metadata-only proposals fail closed without an AgentRunner, TaskPipelineService or
fixed MarketingExecutors fallback. No DB graph rows, Redis wakeups or provider retries
are created by the synchronous path. Transport/timeouts become a typed limitation;
invalid executor contracts still raise internal errors rather than successful output.

Module IDs, evidence and claim IDs are stable for the same actor, request key and
plan using the existing executor identity builder. This is not synchronous persistence
or a promise of deduplicated provider effects. Different model interpretations may
produce different plans/identities.

## Quality boundary and durable path

The application evaluates even typed BLOCKED module outputs, returning their structured
blocking reasons. Failed gates and malformed gate contracts release no success payload.
`module_execution.acceptance.fully_accepted` requires an accepted result and full claim
coverage. For batch manifests, compare accepted IDs intersected with the current
result's IDs to all current claims; unrelated ancestor IDs do not cause rejection.
There is no claim-filtering transformation. Partial acceptance is quality rejection.
The graph worker, graph finish transaction and artifact reload use the same predicate.

```text
ExecutionPolicy.WORKFLOW -> OrchestratorAdapter -> MarketingOrchestratorPlanner
-> PlanCompiler -> GraphExecutionService.start_compiled_run -> WORKFLOW_STARTED
... later, independently ...
ModuleGraphWorker -> COMPETITOR_ANALYSIS -> POSITIONING -> completed
```

The compiler is the execution authorization boundary and uses the existing runtime-owned
`EXECUTABLE_SCENARIOS`; the application keeps no second scenario allowlist. Validated
planning or an intent's scenario name alone grants no execution authority.

The run ID hashes `copilot.run.v1`, actor ID and request key. It deliberately excludes
the plan to reserve the key across plan changes: `start_compiled_run` compares the
immutable persisted compiled plan and raises `StartIdentityConflict` on mismatch.
An identical plan reuses the run, even after completion. `durably_started` acknowledges
that durable identity, not a potentially stale assertion that the run is still queued.
Graph execution, leases, fencing and retries remain owned by the existing runtime.

For `competitive_positioning_v1`, one explicit HTTP(S) competitor source with SITE_FETCH
changes missing OBSERVABLE_EVIDENCE to optional. Its `present` flag remains false until
evidence actually exists. The executor gathers observable evidence; inaccessible sources
block. Existing `new_positioning_v1` still requires pre-collected evidence.

## Verification and limits

`tests/test_copilot_application.py` and `tests/test_marketing_tools.py` cover direct
arithmetic, the three real executors using fake providers, grouped clarification,
stable Quality Gate IDs, source precedence, artifact isolation, unsupported modules,
compiler denial and real/fake partial-claim gate outcomes. `tests/test_copilot_postgresql.py`
starts a real durable run through the application, verifies only the root Job exists,
then explicitly runs the worker to completion. It also verifies replay/conflict,
zero graph entities for synchronous work and rejection of partial claims by graph
finish and worker. Existing architecture tests allow only the explicit new internal
consumers; current guards permit the dedicated production HTTP composition while
forbidding direct execution or database imports from Telegram.

No migration is added; head remains `20260917_0009`. No live paid providers are needed.
Task E verification executed locally: focused execution/regression suites **632 passed**;
final tools/application unit checks **53 passed**; complete Linux Python 3.11 suite with
disposable PostgreSQL 15 and Redis **1170 passed, zero skips**. `python -m compileall app bot`,
`git diff --check` (including staged files) and `alembic check` passed; the latter reported
no new upgrade operations. Existing deprecation warnings remain.

Limitations: three executable modules in the default internal 1.1 composition (six
in explicit production 1.2), narrow deterministic text grammar, no arbitrary artifact
hydration, no durable pre-run clarification, no generic synthesis or push delivery, and
no synchronous idempotency persistence. Provider failures are not retried by this
application service. Quality Gates validate structural provenance, not semantic truth.

Manual internal verification: compose an intent fake, module fake, safe analyzer fake
and shared executor registry; supply a CREATOR request with its scoped inputs and
observe MODULE_RESULT. With a graph service backed by a disposable database and an
existing actor, send comparative positioning context plus URL/SITE_FETCH; observe
WORKFLOW_STARTED before either module executes, then run the separate worker twice.
