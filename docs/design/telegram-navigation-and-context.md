# Telegram navigation and durable project context

## Baseline audit (2026-10-26)

The implementation starts at PR #129 HEAD b04685bc586845592f509eababc5388672852926, with both existing CI jobs passing. Default integration is master; master is an ancestor of that HEAD (14 commits ahead). PR #129 remains open, so this feature is stacked on its branch. PR #130 is an independent output-budget experiment and is excluded. The original checkout and unrelated local files are preserved.

`bot/main.py` routes menu, Copilot, Mentor, workflows, agents, task history, then chat. `OperationGuard` and aiogram event isolation serialize local updates. Copilot pending clarification is presentation state in MemoryStorage, with stable actor/chat/message request identities. Graph execution acceptance is durable in PostgreSQL. Execution receipts in `copilot_execution.v1` are retained for 30 days and prevent reissuing unknown provider outcomes.

`MarketingRun`, `OrchestrationPlanRecord`, `Job`, `JobExecution`, and `MarketingArtifact` own graph/workflow execution. `GraphRunReader` validates saved graph identities and acceptance gates without executing modules. Fixed `marketing_mvp.v1` workflows have independent snapshots and artifacts. Standalone `Task` rows hold saved agent inputs/results. Case Mentor stores questions, explanations, and feedback in a `case_mentor.v1` companion run attached to the graph; it is not an independent project. Its provider packet preserves source/hypothesis labels, limits prior turns to 12 and feedback to five, and never rewrites the strategy. Current Mentor selection is only `mentor_run_id` in aiogram FSM and is lost on restart.

Legacy `Conversation` uses one `tg:<actor>` key, with `Message` referencing it. Its summary/facts are global to the user. They cannot be retrospectively split into projects. New project discussion must not read that global memory or current mutable BrandProfile.

## Required invariants

History, detail, saved result, and context activation call no provider, create no graph run, and enqueue no generation job. Reads never select a project implicitly. Owner verification is performed for each source read and mutation. Telegram private chat identity is checked at the interface and authenticated backend boundary. Selection uses a persisted monotonically increasing version; callbacks generated under an old version fail closed. An accepted execution is independent of navigation and is never cancelled by selecting another project.

Restoration consumes authorized saved data through source adapters. Graph restoration uses the existing strict accepted-artifact reader and Mentor assembly, keeping provenance and separating generated advice from business facts and user reports. Incomplete and malformed sources cannot claim successful continuation. Legacy conversations and insufficient receipts remain read-only. New dialogue is source/thread scoped and bounded, with durable claims and result replay; unknown provider outcomes never authorize an automatic retry.

## Design and rollout

The unified history is a SQL metadata projection over existing source rows, not a copy of result bodies. Initial pages do not assemble a graph or fetch full artifact JSON. Case Mentor companions are folded into source activity; graph execution receipts linked to a graph are excluded. Titles use saved product/task/request metadata and neutral fallbacks, with no title-generation model call. New graph runs persist deterministic `history_title` metadata; receipt display metadata lives beside the response without changing the fingerprint-only input contract.

Additional session/binding/message tables are additive. Apply migrations before deploying new backend containers, then deploy the bot. Old containers retain their existing schemas and source contracts during rollout. Rolling back application code preserves the new tables and saved histories; destructive migration downgrade requires stopping new writers first. No production rollout or merge is part of this task.

## Persistence and ownership

Migration `20261026_0013` adds `project_sessions` (unique owner/public source, mode, title, activity), `active_project_bindings` (actor/private chat, selected session, monotonically increasing version) and `project_discussion_turns` (source session, actor/request key uniqueness, running/completed/unknown claim, fingerprint, question/answer). New owner/type/activity and owner/created indexes cover history selection. The source/result remains in its authoritative existing table. A missing/deleted source is shown as unavailable and can be deactivated; selection never authorizes reading a replacement or foreign source.

Selection validates an authorized, resumable source, then locks User followed by the actor binding and compares `expected_version`. A same-owner source row is checked again under the switch transaction. A successful switch increments the version; clearing selection retains the binding row/version. A concurrent stale switch returns 409. Completed message claims replay only under the corresponding selected source; running/unknown claims do not reissue external work. Provider I/O is outside project claim/completion transactions. Navigating away does not cancel an admitted question; its saved result belongs to the original source.

Updated Telegram clients initialize an isolated epoch zero on their first ordinary chat; the legacy global archive is preserved. An inactive binding creates a new general-chat epoch: `tg:<actor>:new:<version>`. The externally authenticated identity remains `tg:<actor>`; clients cannot submit arbitrary memory keys. `/new` increments the durable version and therefore starts independent temporary conversation facts and transcript, while preserving the legacy `tg:<actor>` archive. The normal chat API rejects bypassing an active project. The existing durable BrandProfile remains an explicit input for newly created work; resumed saved projects use their captured inputs and never import another project's mutable profile.

Admission across Copilot, selected-project and ordinary-chat lanes takes the same short owner lock and checks prior durable identities. A delayed update cannot become another paid request merely by switching modes. Normal CONVERSATION delegation retains the immutable original user message key even when the UI continuation is a callback.

Temporary `chat_execution.v1` MarketingRun receipts protect ordinary-chat Telegram message/action identities. Their input fingerprint includes the resolved conversation scope and exact request. A completed response bypasses ChatService entirely on replay. Running/ambiguous identities are never stolen. Responses are served for 30 days; expired identities remain unavailable and cannot regenerate. A future retention cleanup must retain identity tombstones before removing these records. No receipt is shown as another history project.

## Source adapters and API

History sources are graph (`g:<64hex>`), fixed workflow (`w:<32hex>`), task (`t:<id>`), synchronous receipt (`r:<64hex>`), independent conversation (`c:<epoch>`) and legacy archive (`l:chat`). Case Mentor companions contribute source activity and feedback rather than independent projects. Receipts linked to an existing same-owner graph are deduplicated. Legacy and receipt sources are view-only; a new source-based task is an explicit draft awaiting user text. Completed saved tasks, accepted fixed-workflow results, sufficiently restored conversations and completed strategy graphs can be resumed. Malformed, empty, failed or insufficient data does not claim complete restoration.

All routes require the existing trusted bot bearer credential and authenticated actor header:

| Method/path | Contract |
| --- | --- |
| GET `/projects/history` | Bounded `limit` (1–50), `offset` (0–10000), source/status filters and title-prefix query (100 characters) |
| GET `/projects/items/{public_id}` | Owner-scoped card, capabilities, saved results and latest graph feedback |
| GET `/projects/items/{public_id}/discussion` | Bounded saved discussion page |
| GET `/projects/context?chat_id=…` | Durable selection/version; no full graph assembly |
| POST `/projects/context` | `{chat_id, expected_version, public_id|null, source_public_id?}`; authenticated private chat must equal actor |
| POST `/projects/context/draft` | `{chat_id, expected_version, request_key, text}`; reserve the first exact update and assemble authorized source reference data |
| POST `/projects/context/messages` | `{chat_id, expected_version, request_key, text}`; stable original Telegram identity; bounded text |
| POST `/copilot/execute` | Optional `context_version`; current Telegram captures it for every new request, including plain text; old clients may omit it |
| POST `/chat/message` | Existing DTO plus optional `request_key` and `context_version`; old callers remain compatible, current bot always supplies both |

Foreign/missing source reads return 404, stale selection returns 409, invalid bounded inputs return 422, unknown execution outcome is unavailable. Error responses and logging exclude raw input/provider errors. Navigation does not call Copilot execute, workers or wakeups.

The initial history query projects only scalar metadata in one owner-scoped UNION, without fetching artifact payloads or reconstructing a graph. Cards load their selected result separately. Restoration uses accepted source adapters; actual question admission assembles the bounded provider packet. Title prefix search uses indexed owner-source selection and bounded scalar fields; there is no global full-text search index. Completed/running/failed UI filters group the corresponding native statuses across sources.

## Telegram flows

The reply keyboard combines projects and history into one section and exposes new request, current context, business profile, help and home. Commands remain available. Menu and navigation route before all FSM text; ordinary text checks durable selection before Mentor/Copilot/agent/legacy fallback. Backend lookup failure fails closed. The operation guard keeps read-only menu actions responsive while execution owns the FSM lock; starting a new request waits until accepted local work returns. No accepted backend execution is cancelled by navigation.

Card GET and result viewing never select a project. Resume/new-from-source callbacks include the observed durable version. Binary graph/workflow IDs are base64url encoded, versions use base36, and callback payloads remain at most 64 bytes even at the largest supported version. Old Mentor explanation buttons are read-only and offer a fresh explicit project card. A confirmed switch clears obsolete local action tokens and pending form state. Source-based new work visibly displays its unverified reference metadata and awaits a substantive user request.

Search previews the first eight prefix matches; other history and discussion pages have next/back navigation. Legacy display is an explicitly unsegregated 50-message read-only archive. Initial saved ordinary conversation transcripts have a 50-message display cap; provider restoration uses a smaller 12-message window and bounded summary/facts. Continuing project dialogue retains independently paginated discussion turns. Graph Mentor provider packets retain its existing 12-turn/five-report/section budgets and source labels. Dates are explicitly labeled UTC. Profile editing is a guided form and reads persisted allowlisted fields.

## Branch delivery

The later worktree AGENTS instructions name `sale-ready` as integration. Inspection found it 136 commits and 223 changed files behind the required PR #129 basis. A focused review therefore uses a Draft PR stacked on #129, with eventual integration into sale-ready after the prerequisite branch. No merge or production rollout is authorized by this change.

## Independent review remediation (2026-10-27)

Ordinary chat originally resolved its memory scope before the durable execution claim. A project switch could commit in that gap. The initial read is now advisory: admission locks User, then ActiveProjectBinding, and verifies the inactive binding and exact memory epoch in the same transaction that inserts the running receipt. Switch and epoch-zero initialization follow the same lock order, including when a binding does not exist yet. Stale requests return 409 before ChatService/provider I/O and create no execution receipt. Old clients without a request key receive the same short locked context admission, but retain their historical lack of durable replay. Transactions finish before external calls. A switch after committed admission may proceed while the accepted request finishes in its original scope.

The original Telegram actor/chat/message key remains unchanged across Copilot, project discussion and ordinary chat. Copilot rejects a key already admitted as ordinary chat; a completed Copilot CONVERSATION response can still delegate to chat under the original key and replay its receipt. Running/ambiguous identities cannot be stolen. Ordinary-chat replay remains scoped: a delayed old update cannot surface a different epoch's answer after switching.

A source-based draft is now a backend-owned `project_source_draft.v1` MarketingRun, created atomically with the inactive binding's new version. It stores a bounded snapshot of source public identity, title, goal, description, capture timestamp and `saved_source_reference_unverified` provenance. It is reference data requiring verification, never a new confirmed fact or a mutation of the saved strategy. Owner authorization and capability are checked on creation and source access is checked again during assembly. Drafts are available for 30 days; old rows are not implicitly reused in later epochs.

The next substantive Telegram message reserves the draft for its exact request key and original text. Recreating bot/Dispatcher/backend instances rebuilds the same assembled request from PostgreSQL; later distinct messages do not inherit that draft. FSM carries only the transient assembled-message handoff, not the source of truth. Switching to another project or `/new` invalidates the old draft. Copilot's optional `context_version` fences assembly against admission; the reserved key also requires its original version if a client omits or changes that field. CONVERSATION fallback propagates the original version, and ordinary-chat admission checks the reserved draft epoch again. An already completed Copilot receipt remains replayable without provider work; stale fallback cannot generate in the new epoch.

## Long dialogue memory and follow-up compaction

A checked 40-turn scenario shows that source restoration survives a fresh runtime and A/B switching. Project discussion assembly contains the authorized saved source and the latest 12 completed question/answer pairs (answers truncated to 2,000 characters). These are 12 turns, not 12 individual chat messages. Earlier decisions remain durably available through paginated history but are not automatically returned to the model. Case Mentor independently has a 12-turn window. A resumed ordinary conversation may have a saved source summary/facts, but this does not summarize subsequent project discussion. Opening history performs no generation.

Compaction is deferred to a focused follow-up PR because both project discussion and Case Mentor have different authoritative lineage stores. The follow-up must introduce a versioned, bounded per-owner/per-project summary with a covered-through cursor and source turn/artifact references for every retained decision. Preserve explicit user_reported, user_decision and generated_hypothesis categories; never promote reports/hypotheses to verified facts or rewrite saved strategy. Publish through a short CAS transaction after generation and retain the latest 12 raw turns alongside the summary. Failed/unknown compaction must leave the recent-window fallback usable.

Compaction must have its own opt-in configuration, model/output-token limits, uncovered-turn threshold, per-project cadence, call budget and daily spend cap. It may run only on a substantive question, never on history/navigation. Its budget and telemetry must remain separate from answering the user. Required follow-up tests cover cursor coverage, provenance/source references, A/B and owner isolation, restart, concurrent publication, unknown outcomes, zero calls on reads, and independent budget exhaustion. No compaction provider calls or additional model expense are introduced in PR #131.


## Plain Copilot context admission

For every new private Telegram text, `project_navigation.active_message` reads the durable binding and passes its version with the exact message to `copilot_flow.receive`, including messages without a source draft. The pending payload owns that captured version through URL classification, NEEDS_INPUT answers and retries; later navigation reads do not replace it. `CopilotClient.execute` serializes the optional field without changing the original actor/chat/message request key. CONVERSATION delegation retains the same epoch.

`ExecutionStore.claim` takes User then ActiveProjectBinding locks and checks an inactive binding and exact version in the same PostgreSQL transaction as the durable receipt insertion or revised NEEDS_INPUT claim. An absent binding represents inactive version zero and is fenced by the User lock shared with switches. A completed exact receipt still replays before new-admission validation, and running/ambiguous outcomes are never reclaimed. No lock spans provider work. Clients omitting context_version retain existing admission behavior; reserved source-draft keys keep their separate mandatory version check. No migration or model call is required for validation.


A stale new Copilot admission commits a `copilot_admission_rejected.v1` record before returning 409. It uses the unchanged Copilot execution identity and fingerprint, contains no response or model input, and creates no graph/job. Existing cross-lane identity checks therefore reject the original Telegram update even when a fresh Dispatcher routes redelivery to the selected project or a new inactive epoch. Exact HTTP retry returns stale_context; a payload with a different fingerprint cannot turn that identity into a new execution. Source-draft validation errors keep their precedence. Revised NEEDS_INPUT failures preserve the already durable receipt. Completed replay and unknown outcomes are unchanged.

Rejection records use existing MarketingRun storage and the same 30-day retention as Copilot receipts; keys must not be reused after that window. They are excluded from history and saved-result reads by their separate workflow type. No migration is needed. Older backend readers fail closed on this occupied execution identity (request_conflict), so application rollback does not authorize regeneration. Omitted-version clients creating new identities retain their prior admission contract.
