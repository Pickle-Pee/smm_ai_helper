# Telegram menu and project context acceptance

Status: implementation and independent review complete; final remote CI pending. This is not a production rollout approval.

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
- `python -m compileall -q app bot`, `alembic upgrade head`, `alembic check` (no new operations) and `git diff --check`: passed.
- The initial full attempt encountered Windows default-temp ACL errors; a dedicated disposable basetemp resolved them. A later interruption stopped local test services; they were restarted before the completed full run. These attempts are not recorded as successful full checks.

The required remote Python and container-smoke checks must validate the published revision. Their final status will be linked from the PR.

New deterministic tests cover metadata projection/receipt dedup, mixed-source pagination, context capabilities, owner access, A/B captured assembled context, persisted restart, CAS racing switches, stale buttons, unknown provider outcome, replay, menu/router priority, profile/search/archive rendering and scoped new chat memory. Real Telegram polling and live OpenAI are excluded; providers capture real assembled packets.

## Explicit limits

Title search is a prefix preview of eight results, not full-text search. Legacy global messages cannot be retroactively separated into projects. Legacy and insufficient receipts do not support resume. Initial ordinary-chat/legacy display windows are capped at 50 messages with omission flags; context assembly is bounded. Historical graph records without saved display metadata use neutral titles; no model is called to invent them. Dates are UTC. Old clients omitting ordinary-chat request identity retain their historical API behavior; the updated bot supplies durable identity. New chat receipt cleanup needs identity tombstones before deletion.

Local Docker daemon was unavailable at environment discovery. Native disposable PostgreSQL/Redis checks and remote CI container-smoke are tracked separately. Production readiness requires final green CI plus normal deployment approval; this task performs no merge or rollout.
