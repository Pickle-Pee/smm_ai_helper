# Telegram menu production rollout — DEPLOYED_WITH_LIMITATIONS

Status: **DEPLOYED_WITH_LIMITATIONS**, 2026-10-27. The immutable menu release is
running in production. Mandatory engineering, backup, staging, rollback and live
cutover gates passed. Production acceptance used the actual backend and bot
Dispatcher with a fake Telegram transport and a synthetic operator fixture.
Real Telegram transport and live paid-provider continuation remain unverified.

The [public manifest](telegram-menu-production-rollout.manifest.json) records
public source identities and gate states. Detailed infrastructure, image identities,
package manifests, configuration, backup records and checksums remain in protected
operator storage.

## Release and CI

The release is candidate `420df1ae1b90762a494a3fa95df4ee4fa31ef609`
([PR #134](https://github.com/Pickle-Pee/smm_ai_helper/pull/134)): menu
[PR #131](https://github.com/Pickle-Pee/smm_ai_helper/pull/131), required dependency
[PR #129](https://github.com/Pickle-Pee/smm_ai_helper/pull/129), and the minimal
Alembic driver correction. PR #130 and its output-budget experiment are excluded.
No unrelated sale-ready changes were included in the release candidate.

| Exact source | Required CI result |
| --- | --- |
| Driver fix `173d7613ca2865cfd91ba39dd1febe6505d8165f`, [PR #133](https://github.com/Pickle-Pee/smm_ai_helper/pull/133) | [Run 40569782776](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/40569782776): Python 1,580 passed; container 237 passed; both jobs successful |
| Release candidate `420df1ae1b90762a494a3fa95df4ee4fa31ef609` | [Run 40569594539](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/40569594539): Python 4,391 passed; container 695 passed; both jobs and lifecycle gates successful |

The release CI checkout was inspected. Its tested merge tree equals the candidate
source tree. The independently published sale-ready fix has its own final commit
and CI; it is not substituted for the attested release image. Alembic explicitly
selects the installed synchronous psycopg2 driver; application runtime retains
asyncpg. Original production connection settings and OpenAI configuration were
preserved. Existing model/reasoning configuration, generation limits and graph
scheduling remain unchanged; the dependency adds the intended contextual Mentor
and recovery behavior.

## Confirmed by execution

- Created a consistent protected database backup from an exported snapshot,
  verified its checksum and restored it into a separate network-isolated
  disposable PostgreSQL instance. All 18 table counts and 13 foreign-key
  relationships matched that source snapshot.
- Archived previous application images and configuration with restricted operator
  access. Built, archived and attested the immutable release against 375 source
  files; retained the package manifest in protected storage.
- Passed 94 staging acceptance tests with separate PostgreSQL/Redis, fake providers
  and Telegram transport, isolated ingress and no production polling token.
  Coverage includes menu/history/profile, A/B captured context, restart, ownership,
  stale context/callbacks, duplicate updates, completed replay, unknown outcomes and
  prevention of extra graph/job/provider calls.
- Rehearsed the additive migration from `20261014_0012` to `20261026_0013` on
  restored data. It completed in 5.618 seconds including container startup, with
  a three-second lock timeout and 60-second statement timeout; schema parity passed.
- Rehearsed previous backend/worker/bot images against the expanded schema,
  preserving synthetic new project/discussion records, then restored the candidate.
  No destructive downgrade was used.
- Closed production ingress by holding restart and obtaining normal bot/backend
  exits, including complete backend graceful shutdown and listener closure.
  Dedicated restricted operator credentials performed conditional admission pause;
  the live epoch-fenced drained gate passed before stopping the idle worker.
- Created an additional cutover backup. Applied only additive migration 0013 and
  passed Alembic schema parity. Original table contents matched the cutover
  baseline before reopening ingress, except expected revision/admission changes.
- Started the new worker paused, verified both lanes and Registry readiness,
  passed the live drain gate again, then resumed admission. Started backend,
  confirmed health/readiness, and started the single production bot.
- Ran production smoke through the actual bot Dispatcher and actual backend API
  with fake Telegram transport: `/start`, history, profile, active context and
  `/new`; a synthetic operator-owned saved strategy fixture additionally exercised
  card/result rendering and active-binding changes. Navigation created no jobs
  for that owner and called no generation endpoint. `/new` preserved the saved source.

No forced claim cleanup, old failed-job replay, volume deletion, database rollback
or production OpenAI configuration change was performed. A synthetic technical
user and saved fixture were retained; other users were not targeted by the probes.

## Verified by observation

- Production runs the attested immutable candidate across backend, worker and bot,
  with no observed restarts and only one production bot container.
- Backend health/readiness returned successful responses after cutover; data
  services and worker startup checks passed.
- Production Alembic revision is `20261026_0013`.
- The original production environment fingerprint is unchanged. Effective
  application environment values matched the preserved configuration.
- Protected rollback and backup artifacts remain available. Rehearsal success is
  separate from production rollback: production rollback was not needed or run.

Data-preservation equality was checked while ingress remained closed. Normal
production traffic after reopening may legitimately add or update records; this
report does not claim permanent equality or global inactivity.

## Not verified and remaining limitations

- The user explicitly waived real Telegram transport acceptance. Test probes used
  fake transport; no real Telegram test message was sent. The deployed bot's normal
  polling is separate from these probes.
- The saved strategy opened during production smoke was synthetic and
  operator-owned. An existing real-user strategy was not opened or changed.
- Paid-provider context continuation, live model judgment and semantic quality
  remain unverified. No paid test was authorized or initiated; any future live
  provider smoke requires its own explicit budget.
- Dialogue context retains the source plus its documented bounded recent-turn
  window. Unlimited earlier-decision recall or durable compaction is not claimed.

No further engineering gate is represented as passed by historical CI alone.
Future optional acceptance should use only the controlled operator account;
paid-provider validation remains a separate budgeted action.

## Publication boundary

An earlier version exposed unnecessary operational details. This public revision
omits those details. **Earlier operational details remain accessible in existing
Git commits**; no history rewrite or historical removal is claimed. No credentials
or user payloads were found in the reviewed earlier report; this limited review
is not a claim about the entire repository history.
