# Telegram production runbook

Use with `copilot-production-checklist.md` and the hardening report. This document
does not authorize deployment. Keep one polling bot per Telegram token.

## Configuration and start

1. Record the previous image/code SHA, schema head and worker drain procedure.
2. Verify `DATABASE_URL`, `REDIS_URL`, `API_BASE_URL`, persistent
   `IMAGE_STORAGE_PATH`, `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY` and shared independent
   `BOT_BACKEND_TOKEN` through the approved environment/secret injection. Do not
   paste values into logs or incident reports.
3. Run `docker compose config --quiet`. Start PostgreSQL/Redis and migrations,
   then backend/worker, then bot. This change adds no migrations.
4. Verify backend health/readiness and worker lanes before enabling Telegram ingress.
   Inspect bounded logs for error types, status codes and run IDs, not request bodies.

## Normal use and recovery

- New free text uses Copilot; `/copilot_runs` finds saved graph runs after restart.
  Status callbacks remain valid without Telegram FSM. `/copilot_status ID` opens a
  known graph run. A missing/foreign result returns a generic unavailable message.
- `/runs`, `/status ID`, `/result ID` recover fixed MVP artifacts. `/history`
  recovers standalone tasks. These reads do not repeat generation.
- `/new` clears local clarification. `/cancel` does not cancel an accepted backend
  workflow. During an active serialized request, both commands immediately explain
  that execution is still running; send `/new` after its response.
- Local URL confirmation and repeat-task buttons expire on restart. Suggested-action
  keyboards additionally expire after 15 minutes; capacity eviction or a replacement
  keyboard invalidates them. Reopen a fresh suggestion after expiry.
  Reopen history to request an intentional new repeat. Do not repeatedly start a
  synchronous task after an unknown HTTP outcome; check saved history first.
- Completed graph strategies offer **Объяснить решение**. This saves/opens eight
  sections from accepted strategy/evidence/lineage without provider calls. New
  followup questions invoke the backend model with Expert Core and bounded saved
  dialogue. Text stays bound to that case until `/new` or `/cancel`. After restart
  reopen the strategy and explanation; `/case_history` reads up to 50 saved turns.
- `/case_feedback worked | observations | metrics` records explicit user-reported
  results. Other statuses: applied, hypothesis_tested, did_not_work, corrected.
  For arithmetic supply one labelled cohort, for example: `Расход: 15000 ₽;
  Заявки: 30; Продажи: 3; Период: 1–7 октября`. Missing currency/period, ambiguous
  values and zero denominators require clarification. Feedback is explicitly
  user-reported and reused in subsequent same-case questions; it does not overwrite
  BrandProfile, change the original strategy or prove causality.

## Diagnosing failures

| Symptom | Check / action |
| --- | --- |
| bot fails startup | valid API URL and Telegram token shape, nonempty shared service token; fix injection, never print secrets |
| bot disconnected | Telegram reachability, polling conflict, bounded API errors; one poller per token |
| backend unavailable / timeout | readiness and DB connectivity; inspect `/copilot_runs`, `/runs`, `/history` before regeneration |
| analysis queued | worker lane enabled, drain/pause status, due jobs/leases; Redis wakeup loss alone must not lose PostgreSQL jobs |
| delivery pending/failed | claim lease, claim token, retry count/backoff, Telegram access; `/redeliver ID` for fixed workflow, no generation |
| image unavailable | ownership, persistent shared image volume, allowed backend `/images/*.png`, 10 MiB download cap; reopen saved result |
| mentor unavailable | source must have accepted VIRTUAL_CMO; check backend/DB and provider. Opening a saved explanation/history needs no provider. A new question may have unknown outcome; never clear its claim to force regeneration |
| malformed result | safe user error, run ID/status and deployment SHA for investigation; do not fabricate successful output |

Telegram may accept a message before the database ACK is lost. Lease recovery may
show a duplicate message; at-least-once delivery is not exactly-once visible delivery.
The accepted result remains in history. Never repair this by rerunning generation.

## Graceful stop and restart

Stop ingress and allow/cancel owned bot handlers. The bot drains active update
tasks and delivery before closing its Telegram session. Workers own backend work;
use the existing durable drain controls before replacing them. Restart backend and
worker before bot, preserve PostgreSQL and image volumes, then reopen saved results.
Do not manually mark accepted runs failed because only Telegram stopped.

## Verification and rollback

In an explicitly disposable environment run compileall, pytest with both database
URLs and Redis test URL, `alembic upgrade head` and `alembic check`. CI must also
run container persistence, lane/shutdown and Copilot release checks. No real
provider calls or Telegram sends belong in this verification.

After an authorized deployment verify private-chat start, deterministic calculator,
source classification, graph status/history, explanation/reopen, legacy history and
image retrieval. A live provider request needs separate operator authorization.

Rollback: stop bot ingress, apply worker drain gate, stop app services, restore the
recorded code/images/config, retain schema and persistent volumes, restart backend /
workers / bot. Companion mentor artifacts use existing storage; old code ignores
their workflow type. Do not downgrade migrations or delete runs/artifacts. Capture
SHA, migration head, failing command, status and sanitized IDs when escalating.

## Synchronous result recovery and retention

The uncertainty response for a Copilot request supplies `/copilot_result KEY`.
Use it or repeat the identical payload/key to read a committed response within 30
days. The authenticated read API is GET `/copilot/executions/{request_key}`.
Graph history only lists graph runs; a synchronous module result is stored in its
execution receipt. Receipts expire opportunistically after 30 days. Never reuse an
expired key. Unknown running/ambiguous outcomes fail closed; do not reset claims
or tell users that an external call definitely failed. A new key is new work.

This guarantee does not cache the reply generated after a CONVERSATION delegation
or the initial `/tasks/start`. For legacy chat/task starts check their own saved
history where available; an intentional resend can generate and charge again.

## Independent acceptance gates

Before release inspect `../reviews/pr129-final-acceptance.md` for all 309 original
requirement rows and the exact published candidate CI. Separate engineering
reliability, product-semantic contracts and live acceptance. With separate operator
authorization run the five linked VK/Telegram/audience/budget/measurement questions,
reopen the case after restart, then provide experiment metrics and inspect source
labels, unsupported numeric claims and conditional alternatives. Exercise actual
Telegram sends, media, ACK loss and shutdown in an isolated test deployment.
Fake-model JSON and green CI cannot replace these live quality gates.
