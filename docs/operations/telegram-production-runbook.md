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
- Local URL confirmation, legacy action and repeat-task buttons expire on restart.
  Reopen history to request an intentional new repeat. Do not repeatedly start a
  synchronous task after an unknown HTTP outcome; check saved history first.
- Completed graph strategies offer **Объяснить решение**. This saves/opens eight
  sections from accepted strategy/evidence/lineage without provider calls. Followup
  text stays bound to that case until `/new` or `/cancel`. After restart reopen the
  strategy and its explanation button.
- `/case_feedback worked | observations | metrics` records explicit user-reported
  results. Other statuses: applied, hypothesis_tested, did_not_work, corrected.
  Feedback is reused in subsequent same-case questions; it does not overwrite
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
| mentor unavailable | source run completed with accepted VIRTUAL_CMO; backend/DB available; source remains independently readable |
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
