# First internal module executors

This is an implementation/binding stage. Three real executors are callable by an
internal caller through `ModuleExecutorDispatcher`; there is no user-facing route.
No API, Telegram, MarketingCopilot ingress, Job, worker, MarketingWorkflowService
or generic Orchestrator consumes the executable registry. The fixed MVP still uses
`MarketingExecutors` and its explicit workflow quality adapter. Legacy `/tasks`
still uses AgentRunner. The generic Orchestrator remains `PLANNING_ONLY`.

## Explicit versioning

`ModuleRegistry.load()` and `DEFAULT_REGISTRY_VERSION` remain `1.0.0`: fifteen
metadata-only modules and zero bindings. The original JSON is byte-for-byte
unchanged. `ModuleRegistry.load("1.1.0")` explicitly loads executable metadata;
`EXECUTABLE_REGISTRY_VERSION` names this version. Twelve modules remain metadata-only.
Loading and direct construction reject unknown versions and any different binding
set/key/contract/compatibility. Loading also checks the resource's version against
the requested version. Metadata does not import or discover runtime implementations.

| ModuleId | Exact executor key | Contract | Payload schema |
| --- | --- | --- | --- |
| COMPETITOR_ANALYSIS | competitor_analysis.v1 | module_executor.v1 | competitor_analysis.payload.v1 |
| POSITIONING | positioning.v1 | module_executor.v1 | positioning.payload.v1 |
| CREATOR | creator.v1 | module_executor.v1 | creator.payload.v1 |

All bindings have `compatibility="exact"`. A binding certifies the implementation's
contract mapping, not that every request has sufficient inputs or supported tools.
The factory verifies that its inventory has exactly these implementations, with
matching keys, ModuleIds and contract versions. It creates no mutable global registry.

Normalized SHA-256 uses UTF-8
`json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`:

- `1.0.0`: `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`
- `1.1.0`: `f6f604db27a123ce66edd61424b1f7f8c4cef68fc6e166ff3723bccb3822029c`

Both are pinned in Registry tests.

## Dependency and invocation boundary

```text
ModuleRegistry.load("1.1.0") -> ModuleDescriptor.execution_binding
                                      |
explicit build_module_executor_registry(model_call=..., analyzer=...)
                                      |
                         ModuleExecutorDispatcher
                        /             |             \
            CompetitorAnalysis    Positioning      Creator
                    |                 |               |
                    +------ ExpertInstructionComposer-+
                    +------ injected async model call-+
                    |
             injected exact URL analyzer
                    |
            UrlAnalyzer.analyze_url -> existing safe fetch (DNS/redirect/size bounds)

Each executor -> ModuleExecutionResult + existing Quality Gates contracts
Outer caller (future integration) owns evaluation, retries, persistence and delivery.
```

Example of internal composition (external calls occur only at explicit dispatch):

```python
from app.module_registry import ModuleRegistry
from app.module_execution import ModuleExecutorDispatcher
from app.module_execution.executors import build_module_executor_registry

metadata = ModuleRegistry.load("1.1.0")
executors = build_module_executor_registry(model_call=model_call, analyzer=analyzer)
result = await ModuleExecutorDispatcher(executors).dispatch(
    metadata.get(request.module_id).execution_binding, request,
)
```

`model_call` implements the async `ModuleModelCall` protocol:
`instruction: str`, `text: str`, `response_schema: dict` keyword arguments -> JSON
string. It must make one attempt and enforce the supplied strict JSON schema.
The existing `openai_text.chat` is deliberately **not** the default: it retries and
can downgrade structured output. No configured model/provider is imported by the
new executor package. Tests use fakes exclusively. Passing `None` declares a missing
capability and yields `BLOCKED`, with no calls.

`build_public_site_analyzer()` is an optional, lazy composition helper. It wraps
`UrlAnalyzer` with no cache/database sessions, exactly one URL, and opt-in
`propagate_fetch_errors=True`. It uses the existing public safe fetch boundary and
HTML extraction. The default UrlAnalyzer text/handle extraction and caught-error
behavior remain unchanged for legacy callers. There are no provider calls at
import, construction, registration or lookup. A caller-injected analyzer must honor
the same safe-fetch/single-source/no-retry contract; injection is a trusted internal
composition boundary, not an untrusted plugin execution surface.

## Input mapping and supported scope

Only the supplied `ModuleExecutionRequest` is accepted. Executing another ModuleId
fails before provider invocation. Executors read only objective, expected outputs,
ContextPacket and complete upstream results. They never fetch BrandProfile or
Conversation, query a DB, create Jobs, perform retries or deliver messages.
Caller authorization/scoping remains required; unauthorized facts are additionally
excluded. Duplicate fact/parent claim identities fail closed.

Use existing `PlanningInputKey` tags where available. For slots that have no enum,
use the exact documented `AuthorizedContextFact.label` with `input_key=None`;
arbitrary label aliases/free-text inference do not satisfy structural requirements.
Empty values do not satisfy an input. Existing ContextResolver provenance, such as
`CURRENT_REQUEST:...` or `BRAND_PROFILE:...`, is preserved.

| Executor | Structural inputs / capability |
| --- | --- |
| COMPETITOR_ANALYSIS | Exactly one `competitor_url` string, or one literal HTTP(S) URL in typed `competitor_or_category_scope`; authorized `SITE_FETCH` plus injected analyzer and model |
| POSITIONING | Typed `product`, `target_or_target_hypothesis`, `customer_job_or_need`, `relevant_alternative`, `product_truth`; injected model |
| CREATOR | `product` or exact `product_or_offer`; typed `target_or_target_hypothesis`; `message` or typed `product_truth`; exact `asset_format="text_post"`; injected model |

Competitor names/categories without a URL cannot trigger search discovery and
return `BLOCKED`. Unsafe URL syntax/private literals block before the analyzer;
connection-time DNS/redirect rejection remains the existing safe fetch boundary's
responsibility. An inaccessible/empty page is not fabricated evidence. The first
vertical is observable analysis of one public page; market-wide sets, substitutes,
gaps and differentiation remain explicitly bounded hypotheses. It never establishes
revenue/profit/conversion/internal strategy/success/customer research from page activity.

POSITIONING accepts optional COMPETITOR_ANALYSIS, MARKET_ANALYSIS and other scoped
predecessor results; they do not replace required first-party product truth.
RTB/value proposition/positioning/offer statements must cite local product truth or
proof. Differentiation, points of difference and USP directions are conservatively
restricted to hypotheses in v1; uniqueness is not independently verified.

CREATOR's explicit asset format is a deliberate conservative implementation limit:
an image/video request cannot silently become a text success. Image generation is
not required for text posts. Unknown/missing formats return `BLOCKED` with
`MISSING_CAPABILITY`. Textual scripts/visual briefs/image prompts are concepts only,
never generated media. `post` contains `headline`, `body`, `cta`. Creative output
statements are rationales/choices, not evidence made from the ad copy.
An accepted upstream POSITIONING `target` can supply audience; its
`value_proposition`, `positioning_statement` or `message_hierarchy` can supply message.
When these substitute required context, the result must cite those parent claims.
Failed/blocked predecessors cannot satisfy inputs or become allowed parent IDs.

Missing business inputs return normalized `BLOCKED` with
`MISSING_BLOCKING_INPUT`; absent tools use `TOOL_UNAVAILABLE`; unsupported outputs
or assets use `MISSING_CAPABILITY`; unsafe explicit URLs use `AUTHORIZATION_REQUIRED`.
Blocked payloads contain `missing_or_unsupported`, not a successful module payload.
The normalized status discriminates that variant. No model call occurs on these
preflight paths. Actual provider exceptions/cancellation propagate unchanged once.

## Structured outputs and quality ownership

Dedicated Pydantic schemas forbid extra fields, coercions, blank/oversized text,
unbounded arrays, arbitrary module/runtime metadata and technical ID creation.
Duplicate JSON keys, non-finite constants and malformed JSON fail closed through
`ExecutorOutputError`; provider invocation exceptions are not relabeled as output
errors. Every requested output must have a supported statement, with exact Registry
names (including `differentiation_hypotheses.`, `validation_plan.` and
`creative_hypotheses.`). Unknown outputs/evidence/parent IDs fail closed. Statements
map directly to existing `NormalizedClaim`; no new persistent claim/evidence model
is introduced. Short user-facing rationale is allowed; hidden chain-of-thought is not.

Technical QG IDs use a SHA-256-derived bounded safe suffix incorporating module,
execution ID and local identity, rather than inserting an execution ID into QG syntax.
The caller must supply a distinct execution identity for distinct invocations.

Context evidence is `FIRST_PARTY`, explicitly user supplied and not independently
verified, with original source/fact identity. A fetched page is `EXTERNAL_PRIMARY`
for what is observable on that page, not verification of its advertising claims.
Uncertainty is conservative: zero context confidence maps to UNKNOWN, positive
values below 0.7 to LOW, and values at/above 0.7 to MEDIUM. Page observations cap at
MEDIUM. Each claim's confidence is capped by the weakest cited local support and
parent; hypotheses/inferences/recommendations also cap at MEDIUM. The capped value
is reflected in payload and normalized result. Upstream evidence is not copied into
local evidence; citations use `parent_claim_ids` and `DERIVES`.

Successful results are `PASS_WITH_LIMITATIONS` / `LIMITED`, with deterministic scope
limitations and supplied assumptions represented using the existing contracts.
These are module-declared outcomes, **not** QualityGateEvaluator decisions. Neither
executor nor dispatcher invokes the evaluator. An outer caller can evaluate the
complete lineage batch against the unchanged default Registry `1.0.0` metadata;
the evaluator itself still rejects executable Registry versions. Structural/provenance
checks do not prove semantic truth or detect every fabricated sentence. The prompts
prohibit fabricated offers/proof and treat objective, websites, upstream payloads
and facts as untrusted data. Semantic evaluation remains an outer concern.

## Verification and next step

`tests/test_module_executors.py` exercises all three real executors through Registry
bindings/factory/dispatcher with injected fakes, input/tool blocking, strict schema
rejection, provenance, lineage, confidence, single-attempt failures, exact URL scope,
no import-time runtime owners and outer Quality Gates compatibility.
Registry tests pin both checksums, defaults, exact approved inventory, unknown-version
failure and unchanged descriptor metadata. Existing foundation, Copilot, planner,
Quality Gates and fixed workflow suites remain compatibility coverage.

Local verification on the repository `.venv`:

- Focused suite (execution, Registry, executors, orchestrator, Copilot, all Quality
  Gates, workflow and marketing MVP tests): **722 passed, 14 skipped**.
- `.venv/Scripts/python.exe -m pytest`: **1030 passed, 42 skipped**.
- `.venv/Scripts/python.exe -m compileall app bot`: passed.
- `git diff --check`: passed.
- Diff against base `185d7872089e252e283a29d331047b99396a5f2b` for Registry
  `v1.0.0.json`, fixed `executors.py`/`quality.py` and migrations: empty.

Local skips require explicitly configured disposable PostgreSQL/Redis services;
Docker daemon was unavailable. Existing deprecation warnings remain. No live model,
paid API or external website calls were made by these tests. Review checked exact
binding inventory, default compatibility, single-attempt exceptions, scope/lineage,
no evaluator calls and no existing production consumers. The exact-URL regression
also prevents discovering extra handles embedded in a supplied URL's query.

No migrations or ingress/worker integration are included. Next task: PlanCompiler /
generic graph execution integration, including outer quality evaluation and explicit
decisions about durable execution and eventual fixed-workflow migration.
