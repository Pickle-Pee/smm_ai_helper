# Telegram menu and project context acceptance

Status: implementation and independent review complete; validation gates and live CI evidence are recorded below. This is not a production rollout approval.

## Implemented scenarios

Private Telegram /start/native commands open the persistent menu; menu text never becomes an LLM prompt. One Projects and history view supports compact pages, source/status filters, prefix search, cards, saved result viewing and explicit continuation. Read-only navigation remains available during a local running operation. Business profile fields can be read and edited without calling a provider. New request clears selection only after a confirmed backend CAS and preserves saved work.

Graph strategy continuation uses existing Case Mentor and accepted source lineage. Fixed workflows, saved tasks and independent ordinary dialogues have authorized source adapters and isolated project discussion. Legacy global chat and synchronous receipts remain honestly view-only. Mentor questions/feedback belong to their original case, and linked graph receipts are not duplicate projects.

Active selection survives service/dispatcher restart in PostgreSQL. Source ownership, private-chat identity, callback versions, duplicate updates, successful replay and unknown outcomes are checked at backend boundaries. A new generic chat epoch after /new does not read legacy or a prior epoch. Admitted generation belongs to its original source even if selection changes. Navigation creates no provider call, graph run or generation job.

## Migration and compatibility

Additive revision `20261026_0013` creates project_sessions, active_project_bindings and project_discussion_turns plus history indexes. Existing source tables, historical messages and worker contracts are preserved. The ordinary chat DTO adds optional request_key/context_version; current Telegram sends both. Apply schema before backend, then bot; rollback application first and preserve new tables. Migration downgrade requires stopping new writers and discards new discussion/selection state, so it is not a runtime rollback mechanism.

## Review and verification

Independent review identified and corrected legacy archive rendering and completed-status grouping. The inherited duplicate ordinary-chat path is protected by durable execution receipts. Final review also closed callback-vs-original-message identity drift and cross-mode redelivery: all three admission lanes serialize on the owner and reject identities previously claimed by another mode, while allowing ordinary CONVERSATION delegation. Updated first-time Telegram chat initializes isolated epoch zero instead of appending to the legacy archive. Local verification completed on disposable PostgreSQL/Redis with external providers disabled:

- Full pytest command (`-q --tb=short -o faulthandler_timeout=120 --durations=15`, dedicated `--basetemp`): 4351 passed, two obsolete contract expectations failed (old Alembic head and missing adapter request_key). Both expectations were updated to verify the new contracts.
- Post-fix focused run over all new suites plus affected PostgreSQL/architecture/security suites: **620 passed**. This includes epoch-zero legacy preservation, sanitized provider errors/unknown replay, actual Dispatcher A/B restart with feedback, and both previously failed scenarios.
- Earlier cross-lane/callback/Copilot/Mentor regression run: **480 passed**.
- Final task-ID boundary/history/navigation regression run: **68 passed**.
- Non-UTC database timezone, history and project-restoration regression run: **45 passed**. Existing naive UTC source timestamps are explicitly normalized before comparison with timezone-aware session activity.
- `python -m compileall -q app bot`, `alembic upgrade head`, `alembic check` (no new operations) and `git diff --check`: passed.
- The initial full attempt encountered Windows default-temp ACL errors; a dedicated disposable basetemp resolved them. A later interruption stopped local test services; they were restarted before the completed full run. These attempts are not recorded as successful full checks.

The required remote Python and container-smoke checks validate each published revision. Their authoritative current status and exact SHA are available in [Draft PR #131 checks](https://github.com/Pickle-Pee/smm_ai_helper/pull/131/checks). A final boundary probe also reproduced oversized PostgreSQL INTEGER task IDs returning an SQL binding failure; the parser/Telegram codec now reject them before SQL with 404, with regression coverage.

New deterministic tests cover metadata projection/receipt dedup, mixed-source pagination, context capabilities, owner access, A/B captured assembled context, persisted restart, CAS racing switches, stale buttons, unknown provider outcome, replay, menu/router priority, profile/search/archive rendering and scoped new chat memory. Real Telegram polling and live OpenAI are excluded; providers capture real assembled packets.

## Explicit limits

Title search is a prefix preview of eight results, not full-text search. Legacy global messages cannot be retroactively separated into projects. Legacy and insufficient receipts do not support resume. Initial ordinary-chat/legacy display windows are capped at 50 messages with omission flags; context assembly is bounded. Historical graph records without saved display metadata use neutral titles; no model is called to invent them. Dates are UTC. Old clients omitting ordinary-chat request identity retain their historical API behavior; the updated bot supplies durable identity. New chat receipt cleanup needs identity tombstones before deletion.

The first remote container run passed the real PostgreSQL/Redis pytest group and persistence/worker-lane checks, then exposed an offline transport allowlist that rejected the newly required SetMyCommands startup call. The CI fake now permits only the exact private-chat command menu, with regression tests preserving rejection of other methods.

Local Docker daemon was unavailable at environment discovery. Native disposable PostgreSQL/Redis checks and remote CI container-smoke are tracked separately. Production readiness requires final green CI plus normal deployment approval; this task performs no merge or rollout.

## Staging verification procedure

After the normal staging deployment approval, apply migrations before backend/bot. In a private chat open /start; use history/cards/result viewing and confirm no provider/job creation. Select contradictory saved cases A and B, ask a case-specific question and verify captured provider context contains only the chosen case. Restart backend and dispatcher with the same PostgreSQL, then send plain text without a source ID. Verify retained selection, discussion and feedback. Try the old A activation button after selecting B: it must fail; /new must preserve both histories and start a fresh ordinary-chat epoch. Cross-owner source reads/activation must return404. These steps supplement automated acceptance; no production rollout was performed.

## Independent review remediation - audited db3a2a8 (2026-10-27)

### P1: ordinary-chat context admission

Cause: `resolve_scope()` released its transaction before `_claim()`, which checked update identity but not active binding/version. Controlled PostgreSQL HTTP tests pause at this boundary, commit activation, activation followed by deactivation, or `/new`, then release the old message. On the audited code all three returned 200 and reached the fake pipeline. The fix checks inactive binding and exact epoch under User -> ActiveProjectBinding locks inside durable admission. Switch and first-epoch initialization use the same lock order. Old unkeyed clients also perform short locked admission. No transaction spans provider work.

Regression: `tests/test_chat_context_admission_postgresql.py` asserts stale 409, zero provider calls/receipts, exact-key redelivery rejection, a single ordinary/Copilot admission winner, and switching while admitted provider work is paused. Existing chat/ProjectDiscussion/Copilot suites verify completed replay, unknown/expired outcomes, CONVERSATION delegation, owner isolation and competing switches. Copilot cannot create a new execution from an ordinary-chat identity.

### P2: source draft survives restart

Cause: `navigation_seed` lived only in MemoryStorage FSM and disappeared on restart. The backend now persists an owner/version-scoped bounded source draft atomically with the switch. Assembly includes source identity, capture time and unverified provenance. The first exact Telegram update reserves the draft; recreation rebuilds the same request. Later updates/new epochs cannot silently inherit it.

Regression: `tests/test_source_draft_postgresql.py` chooses a source through an actual Dispatcher and authenticated ASGI backend, closes Dispatcher/storage, recreates backend and Dispatcher, sends text and captures the interpreter's real assembled input. It asserts source A/provenance, no B, exact key/version and provider-free replay. Further checks cover foreign ownership, deleted sources, modified text/key, A/B switching, `/new`, and a controlled switch after assembly before Copilot admission, including public HTTP 409. Omitting the optional version cannot bypass a reserved draft. CONVERSATION fallback preserves its epoch, and ordinary admission rejects the draft key in a forged current epoch before generation.

### P2: long dialogue continuity - explicit limitation

Cause: project assembly loads a fixed 12 completed-turn window with no durable summary of earlier discussion. `tests/test_project_dialogue_continuity_postgresql.py` completes 40 sequential messages, switches A/B/A and recreates the runtime. Assembly includes original saved facts and exactly the latest 12 question/answer pairs. An early user decision remains in paginated history but is absent from model input. It verifies isolation, unchanged saved source, hypothesis labels and zero generation on navigation/history.

Compaction is deferred to a focused follow-up PR: schema/coverage publication, source references, provenance and a distinct cost-control contract across project discussion and Case Mentor would broaden this remediation. The bounded design and follow-up gates are specified in `docs/design/telegram-navigation-and-context.md`. Current PR adds no compaction/model expense and explicitly protects the limitation with a regression test.

### Remediation verification

Post-fix real PostgreSQL verification: the four focused chat-admission/chat-execution/source-draft/continuity suites passed (19 tests); the final source-draft/Copilot API/Telegram Copilot batch passed (201 tests). Compileall, Alembic upgrade and schema parity passed. Full Python and container lifecycle results for the published revision are tracked in [PR #131 checks](https://github.com/Pickle-Pee/smm_ai_helper/pull/131/checks). All providers and Telegram transports are fake; OpenAI points at a loopback discard endpoint. Migration `20261026_0013` is unchanged; drafts use existing durable storage. Work starts exactly at the audited PR #131 HEAD and excludes PR #130. No merge or deployment is performed.


The exact published remediation revision was rechecked with 99 integration/Dispatcher tests (passed). The first remote run completed container-smoke: **684 passed**, plus successful persistence, Redis/worker recovery and real container SIGTERM/restart. Its full Python run reported **4372 passed / 1 failed**: the remaining assertion enumerated the old ExecuteRequest fields. It now explicitly checks additive optional context_version and unchanged legacy serialization/fingerprinting. The final revision reruns both complete CI jobs; use the linked PR checks for its exact-head verdict.


## Final admission gap - reviewed d7da5cd (2026-10-27)

Ordinary Telegram text previously lost the checked binding version because navigation only handed context_version to Copilot for a source-based draft. Every new text now carries its observed version through navigation -> Copilot pending payload -> CopilotClient -> ExecutionStore. Clarifications and retries keep the initial version. Durable admission validates exact version and inactive selection under the existing User -> ActiveProjectBinding lock order, in the receipt transaction. Missing binding is initial inactive version zero, protected by the same User lock as binding creation. Existing omitted-version API clients, fingerprinting, identity, completed replay and unknown-outcome handling retain their contracts. No schema change or additional LLM call is introduced.

`tests/test_copilot_context_admission_postgresql.py` uses an actual Dispatcher, authenticated ASGI HTTP, production Copilot composition, a dedicated disposable PostgreSQL database and fake providers. It pauses after the navigation check before claim, commits activation, activation/deactivation or /new at versions zero and one, and requires HTTP 409 stale_context, zero interpreter/module calls and no graph/job; only the rejected admission identity is persisted. Exact original HTTP redelivery retains its epoch and also returns 409 without provider work. Controls cover no switch, CONVERSATION epoch propagation, completed/saved replay after selection changes, old omitted-version clients and genuine strategy NEEDS_INPUT continuation with/without /new. Source drafts and unknown outcomes are additionally covered by their existing PostgreSQL suites. The new suite is included in both Python CI and container-smoke.

Validation is performed with OPENAI_BASE_URL pointing to loopback discard and fake Telegram transport; no paid calls, merge or deployment. Final full Python/container-smoke results belong to this PR's current SHA and are available in [PR #131 checks](https://github.com/Pickle-Pee/smm_ai_helper/pull/131/checks); historical results above are not evidence for the new revision.

Local evidence for this fix: the activation race was run against the reviewed d7da5cd navigation/admission files and failed with HTTP 200 instead of 409; restoring the patch made the focused/neighbor batch pass (**171 passed**). The batch includes all 11 new cases, source drafts, sync replay/unknown outcomes, chat admission, cross-lane identity, Telegram Copilot and API suites. Dedicated database: smm_mvp_test_pr131_admission (separate from application data). Final diff review preserves lock order, optional legacy serialization, original key/fingerprint and claim-before-provider boundaries.


The repeat-delivery check also recreates Dispatcher/FSM and feeds the actual original Telegram update. A first implementation that only passed the version returned 409 correctly but allowed this redelivery to call the selected-project fake provider once. The regression reproduced that call against `facd24c` admission. Final admission persists a `copilot_admission_rejected.v1` tombstone with the same request identity/fingerprint before sending 409; existing project/chat identity fences then prevent cross-lane generation after restart. Rejected identities are not history projects or saved responses, expire under the existing 30-day receipt policy, and need no migration. An older backend rejects the occupied identity rather than generating. Source-draft omission errors, NEEDS_INPUT receipts, completed replay and unknown outcomes retain their precedence.

The final expanded local boundary batch again passed **171 tests**. Full CI for the first version-only implementation was **4384 Python tests / 695 container tests**, plus persistence, Redis/worker and SIGTERM/restart checks ([run 40525510922](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/40525510922)); those results are superseded by the final-head rerun for the added durable redelivery guard. The optional concurrent native full run was stopped before completion when this guard was added and is not claimed as a pass. The required full Python and container lifecycle checks run on the final revision, linked through PR checks above.
