# Production Copilot HTTP API

The dedicated API connects the existing internal Copilot to production capabilities.
It does not replace ChatService, TaskPipelineService or MarketingWorkflowService.
Telegram remains disconnected; no `bot/**` changes or polling are needed.
Storage uses existing User, BrandProfile, MarketingRun, Job, JobExecution,
OrchestrationPlanRecord and MarketingArtifact models; there is no migration.

```text
HTTP caller -> require_actor -> internal User.id
 -> BrandProfile + explicit business context + optional owned-page acquisition
 -> MarketingCopilotService
      DIRECT -> deterministic calculator -> 200 presentation
      SINGLE -> executor -> full Quality Gates -> 200 presentation
      CONVERSATION -> 200 legacy_chat delegation
      NEEDS_INPUT -> 200 grouped business clarification
      WORKFLOW -> compiled plan -> PostgreSQL Jobs -> graph Redis hint -> 202
          -> production graph worker -> persisted accepted artifacts
GET /copilot/runs/{run_id} -> owner/type check -> accepted-artifact validation
 -> deterministic strategy / experiments / research / limitations
```

## Authentication and identity

Both endpoints require `Authorization: Bearer <BOT_BACKEND_TOKEN>` and
`X-Telegram-User-ID: <positive Telegram integer>`, exactly as existing authenticated
routes do. The actor header alone grants no access. This is a trusted backend-client
boundary; do not distribute the shared backend credential to browsers/end users.
POST resolves or creates User atomically with `INSERT ... ON CONFLICT`; Copilot
receives the internal primary key, not the Telegram ID. GET joins the owner User
without creating an identity. Foreign, missing and non-graph runs all return 404.

## Request contract

`POST /copilot/execute` accepts `ExecuteRequest` in
`app/marketing_copilot/api_contracts.py`. Extra fields and coercion are forbidden.
OpenAPI is the executable schema. No arbitrary nested JSON context is accepted.

```json
{
  "request_key": "strategy-2026-01",
  "message": "Build a marketing strategy",
  "context": {
    "business_goal": "Grow qualified bookings",
    "product": "Appointment scheduling software",
    "target": "Independent clinics",
    "customer_job_or_need": "Reduce scheduling work",
    "relevant_alternative": "Manual spreadsheets",
    "product_truth": "Appointment reminders are available"
  },
  "competitor_urls": ["https://competitor.example/"],
  "market_sources": [{"title": "Supplied study", "excerpt": "Clinics report scheduling delays."}]
}
```

| Field | Contract |
| --- | --- |
| `request_key` | Required, 1–128 ASCII letters/digits/`_.:-`, starts with letter/digit |
| `message` | Required, nonblank, at most 12,000 characters |
| `context` | Optional typed object; each value null or text up to 4,000 characters |
| `owned_site_url` | Optional explicit owned source, at most 2,048 characters |
| `competitor_urls` | Explicit competitor sources, at most 3 URLs |
| `market_source_urls` | Explicit research sources, at most 3 URLs |
| `market_sources` | At most 8 supplied excerpts; title 300, excerpt 8,000 characters |
| `confirmation` | Optional snapshot confirmation, requires owned_site_url |

Other context fields are `existing_proof`, `geography`, `economics`, `message` (creative
message), and `tone`. `target` maps to the existing `target_or_target_hypothesis` slot.
Source roles are never guessed from URLs in free text. The server supplies provenance,
fact identities, sensitivity, authorization, relevance and source classes. Supplied
market excerpts use EXTERNAL_SECONDARY; the client cannot claim EXTERNAL_PRIMARY.
The serialized request budget is 128 KiB; NUL/unpaired-surrogate text is rejected.
This is a validated DTO budget, not a replacement for deployment HTTP body limits.

BrandProfile maps saved product description, audience, tone, goals and an allowlist
of scalar business fields into the existing resolver. Current explicit values, including
empty/null masks, retain precedence over owned descriptive context and BrandProfile.
BrandProfile product description and owned observations never automatically become
product_truth. No project/conversation context injection is exposed in this API version.

## Owned-page confirmation boundary

The API invokes OwnedProductEvidenceService before Copilot, using the existing safe
UrlAnalyzer and a strict extractor over the existing text transport. The worker never
fetches owned context. Source outcomes remain ACQUIRED, UNSAFE_SOURCE,
SOURCE_UNAVAILABLE, EMPTY_CONTENT, CAPABILITY_UNAVAILABLE or INVALID_EXTRACTION.
An extractor outage is a typed source outcome; unrelated programming defects propagate.

A NEEDS_INPUT response includes `owned_site.snapshot_id` and bounded candidates:
`statement_id`, `field`, literal `statement`, `source_url`, `trust: site_claim`.
Candidates include only observed product/service, capabilities and value propositions.
Audience, customer jobs, prices, positioning and proof are ineligible for product_truth.
Confirmation means the authenticated caller attests selected product claims; it never
converts website claims into independent research evidence.

Resubmit the same owned URL with business context and:

```json
{
  "snapshot_id": "owned_<returned identity>",
  "statement_ids": ["stmt_<returned identity>"],
  "confirmed": true,
  "reference": "I verified these product capabilities"
}
```

This object is the `confirmation` field, not a complete execute request. Copy actual
returned identities. `confirmed` requires the literal boolean true; 1 is not accepted.
The API re-acquires/re-extracts the page and compares the exact snapshot identity.
Changed or unavailable snapshots produce 409 `confirmation_changed`, with fresh
candidates when available. Unknown/ineligible statements produce 422
`invalid_confirmation`. Only a matching valid selection projects a confirmed fact;
`confirmed_by` is server-generated from internal User.id. Explicit current
product_truth, including empty/null, still takes precedence.

No snapshot persistence/cache is added. Snapshot identity includes extraction as well
as page content, so nondeterministic extraction can require reconfirmation even on an
unchanged page. This deliberately fails closed. Reusing a key before durable start is
permitted; after start it is subject to exact effective-plan idempotency.

## Response contracts

All public values have `schema_version: copilot_api.v1`. POST uses a discriminated
union with `kind`; optional owned acquisition information appears under `owned_site`.

| Kind | HTTP | Payload |
| --- | --- | --- |
| DIRECT_RESULT | 200 | `calculation`: type, decimal-string inputs/outputs, formula, assumptions |
| MODULE_RESULT | 200 | `result`: ready post headline/body/cta or bounded findings/sources/limitations |
| CONVERSATION | 200 | `delegate: legacy_chat`; no hidden ChatService call |
| NEEDS_INPUT | 200 | Safe code, grouped `alternatives`, actions and optional confirmation candidates |
| WORKFLOW_STARTED | 202 | `run_id`, `status: ACCEPTED`, relative `status_url` |
| ERROR | 404/409/422/503 | Allowlisted code and optional fresh owned acquisition information |

DIRECT and SINGLE do not create runs or Jobs. SINGLE presentation requires full
result-and-claim acceptance, not merely a successful model call. CREATOR renders a
post; COMPETITOR_ANALYSIS/POSITIONING render findings, safe source summaries and
limitations. Decimal strings preserve calculator precision. The existing calculator
grammar remains unchanged (for example `Рассчитай лиды при бюджете 100000, CPC 50 и
конверсии 5%`). Typed numeric inputs are not added in this HTTP version.

`GET /copilot/runs/{run_id}` accepts a 64-character lowercase hexadecimal run ID.
Its response has `run_id`, stable status, nullable `strategy` and `experiments`, bounded
`details`, nullable `evidence_coverage`, `limitations` and nullable `failure`.
Statuses are QUEUED, RUNNING, COMPLETED, COMPLETED_WITH_LIMITATIONS, BLOCKED and FAILED.
NEEDS_INPUT occurs before graph start and is not a persisted graph status.

Strategy maps all nine accepted VIRTUAL_CMO outputs: strategic_diagnosis,
main_growth_constraint, strategic_priorities, trade_offs, resource_priorities,
strategic_bets, roadmap, risks and decision_triggers. Each includes text/items.
EXPERIMENTS remains a separate designs list; research/positioning findings remain
bounded details. No synthesis model call is made. Partial accepted research can appear
while a run is active; strategy is present only after its artifact is accepted.

Coverage shows competitors supplied/accepted and safe limitations. Optional competitor,
market or experiments failures remain visible with COMPLETED_WITH_LIMITATIONS. Absent
optional research can still yield COMPLETED with explicit coverage limitations.
BLOCKED returns `context_required` and review actions; FAILED returns
`result_unavailable` and support/retry actions. Raw run.error is never returned.
Internal claim/result/batch/fact IDs, bindings, Expert Core metadata and raw model
envelopes are excluded. Public page source references omit query strings/fragments.

## Composition, transactions and errors

`production.py` uses the PR #63 graph composition: Registry 1.2.0, all six exact
executors and `smm:orchestration:wakeups:v1`. Construction validates capabilities
without provider calls; the API process creates no worker. Its Redis pool closes
on FastAPI shutdown. PostgreSQL due scans recover missed wakeups independently.

Identity/BrandProfile are read in a short transaction, closed before owned fetching,
intent or module calls. Graph start owns its durable transaction. GET uses a
REPEATABLE READ READ ONLY transaction and reuses the runtime's `_plan`/`_graph_state`
validation (a deliberate shared internal read boundary) to verify plan identity,
artifact fingerprints and full-claim acceptance. It does not claim, wake or update.
Invalid persisted contracts fail closed with a safe 503 instead of releasing artifacts.

Intent/extraction use thin adapters over the existing single-attempt strict Responses
transport; nullable intent properties are required on the provider wire. No SDK,
fallback, repair or application retry stack is added. Before durable start, expected
provider/structured-output failures become 503 `temporarily_unavailable`; owned
extractor failures instead become source outcomes. The complete pre-start application
operation is bounded by GRAPH_TIMEOUT_SECONDS, excluding the identity transaction.
Programming defects retain the normal 500 boundary. Worker failures use durable
attempt/retry rules from the production worker contract.

Other errors: 409 `request_conflict`, 404 `not_found`, 422 `invalid_request` or
`invalid_confirmation`. HTTP validation never echoes submitted values. Authentication
uses existing 401/503 `detail` responses. Logs contain safe actor/request/result/run
identities and timings; messages, prompts, fetched pages and product truth are excluded.

Same internal actor + request_key + effective compiled plan returns the same run and
does not duplicate Jobs. A changed compiled plan returns 409. Changes in saved brand
context or owned extraction can therefore conflict; use a new key for new work.
This is durable workflow idempotency, not a cached response or exactly-once provider
execution promise for synchronous operations. Semantic interpretation runs again on
replay, so a changed interpreted plan also conflicts safely.

## Verification

`tests/test_copilot_api.py` covers strict DTOs, auth, safe error boundaries, confirmation
eligibility and lazy coherent composition. `tests/test_copilot_api_postgresql.py` covers
HTTP DIRECT/SINGLE/delegation, BrandProfile precedence, identity, ownership, idempotency,
owned confirmation/reacquisition, and production worker completion/optional failure
using real PostgreSQL/Redis and fake provider HTTP transport. Polling checks assert
unchanged model calls, Jobs, run timestamps and wakeups.

Use disposable stores configured by MVP_TEST_DATABASE_URL, DURABLE_JOB_TEST_DATABASE_URL
and REDIS_TEST_URL, then run `python -m pytest`, `python -m compileall app bot`,
`git diff --check`, and `alembic check`. CI runs the API tests inside the built image,
checks router presence and validation through the live backend, recreates backend and
worker to verify persistence, and verifies both worker lanes/Redis recovery/shutdown.
No Telegram polling or live paid provider is used.

For manual verification with configured capabilities: authenticate, POST the strategy
example, poll status_url until terminal, repeat the same request, then change
product_truth under the same key to observe 409. Poll as another actor to observe 404.
Repeat without product_truth and with owned_site_url to exercise the confirmation flow.
