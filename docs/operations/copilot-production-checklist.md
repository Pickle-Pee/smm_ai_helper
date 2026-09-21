# Copilot production checklist — Task L

Base: `1fb46fd3a923620f41e9d5072d394115e9c88e04` (PR #65 merged into `sale-ready`).
This change hardens recovery and operation; it adds no marketing module or scenario.
The separate `sale-ready -> master` release requires Task L review and explicit approval.

## Configuration and deployment

Use an immutable application image/tag for backend, worker and bot. Save the previous
image digest before rollout. Keep `.env` outside source control and logs.

| Setting | Requirement |
| --- | --- |
| `DATABASE_URL` | PostgreSQL URL; persistent database/volume is the truth store |
| `REDIS_URL` | Redis wakeup transport; unavailability degrades latency, not durability |
| `BOT_BACKEND_TOKEN` | Independent non-empty shared service credential, identical in backend/bot |
| `TELEGRAM_BOT_TOKEN` | Valid Telegram bot token, required by bot startup |
| `API_BASE_URL` | Bot-accessible HTTP(S) backend URL, normally `http://backend:8000`; no credentials/query/fragment |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | Text provider credentials/base URL; no provider request during startup or readiness |
| `DEFAULT_TEXT_MODEL_HARD` | Non-empty model name supporting existing strict structured output |
| `IMAGE_STORAGE_PATH` | Shared persistent backend/worker media volume for retained legacy images |
| `HTTP_TIMEOUT` | Positive provider timeout, default 60 seconds |
| `GRAPH_TIMEOUT_SECONDS`, `GRAPH_LEASE_SECONDS` | Defaults 300/330; provider timeout < execution timeout < lease |
| `WORKER_CONCURRENCY`, `GRAPH_WORKER_CONCURRENCY` | Independent fixed/graph lane counts, defaults 2/1, each 1–8 |

Other legacy settings remain in `.env.example`. Backend startup checks its service
credential and constructs the production Copilot. Worker startup checks Registry
**1.2.0**, exactly **six** bindings, capability coherence, distinct canonical queues
and timeout/lease ordering. Bot startup rejects malformed URLs/tokens. Configuration
errors hide input values; never print settings/environment objects for diagnostics.

Queue keys are fixed: `smm:marketing:wakeups:v1` and
`smm:orchestration:wakeups:v1`. Do not point the two lane families at one key.

Deployment order, using the existing Compose deployment:

1. Back up PostgreSQL and retain the shared image volume. Verify the target image/tag.
2. Start PostgreSQL and optionally Redis: `docker compose up -d db redis`.
3. Apply migrations: `docker compose run --rm migrate` (`alembic upgrade head`).
4. Start backend and worker: `docker compose up -d backend worker`.
5. Check `/health` and `/ready`, and worker startup lane/Registry logs.
6. Start bot: `docker compose up -d bot`; verify private-chat commands.

No migration is introduced by Task L. Current Alembic head remains
`20260917_0009`; `alembic check` must report no upgrade operations. This is an
additive API/UX change with no existing DTO field renamed.

## Liveness, readiness and outages

`GET /health` returns 200 for process liveness. `GET /ready` returns 200 only after
composition is initialized and PostgreSQL answers a `SELECT 1` within a three-second
budget; failure returns a generic 503. Compose uses `/ready`. Readiness makes no
paid provider or Telegram call and does not depend on Redis. Redis outage is an
operationally degraded state while readiness can remain green. A healthy readiness
response does not prove credentials are accepted by remote providers.

Before durable start, database failure returns safe 503, never a fabricated run.
Uncertain HTTP outcomes should be retried with the same logical request key, or
resolved through run discovery. A lost commit acknowledgement may still mean the
database committed. During worker persistence failure, the iteration logs exception
type and retries the loop; the unfinished lease remains recoverable. PostgreSQL
loss requires operator/database recovery, not application reconstruction of data.

Redis wakeups happen after commit and are best effort. Every worker loop scans due
PostgreSQL Jobs before waiting for hints. Lost, duplicate or stale hints do not own
execution. Redis may remain unavailable throughout a successful graph.

## User recovery and delivery guarantees

Primary free text goes Telegram -> authenticated HTTP Copilot API ->
MarketingCopilotService. Only `CONVERSATION` delegates to legacy `/chat/message`.
Explicit `/analyze`, `/runs`, task/history and image commands retain their legacy
paths. Old fixed runs are never redirected into the graph runtime.

`GET /copilot/runs?limit=10&offset=0` returns the authenticated internal owner's
`orchestration_graph.v1` runs, ordered by creation time and ID descending. Items are
only run ID, status and UTC timestamps. Limit 1–50, offset 0–10000, nullable
`next_offset`. No owner ID, input/state/error, job payload, fingerprint or executor
information is returned. Existing owner/type indexes suffice for this bounded MVP
baseline. New runs can shift offset pages; use `/copilot_status <run_id>` for a known
older run. This is not an unbounded export API.

In Telegram, `/copilot_runs` reconstructs buttons from that durable list without
MemoryStorage. Selecting a run reads `GET /copilot/runs/{run_id}` and revalidates
accepted artifacts before rendering status/strategy/experiments. A failed or blocked
run has a safe explanation; it is never presented as successful strategy completion.
The user may return after any process restart. A crash between backend acceptance
and Telegram acknowledgement is **at-least-recoverable**, not **exactly-once** delivery.
Presentation may be repeated; no extra model call is used to render saved artifacts.

Pre-run clarification, URL classifications, unconfirmed observations/selections and
the local event ledger intentionally remain ephemeral. They are not durable work
until WORKFLOW_STARTED. After bot restart the user starts again. Old callbacks fail
closed; a per-dialog random nonce prevents old buttons matching even if the same
Telegram update rebuilds the same request key/revision. The nonce never changes the
backend request key. A new text message after restart is a new request, not a resumed
confirmation. A new DB table solely for transient selections is not justified for MVP.

Same actor + request key + effective plan returns one run/revision and one Job per
node identity. A different effective plan under that key returns 409 request_conflict;
there is no last-write-wins. Reinterpretation or changed saved context may cause a
safe conflict. Synchronous DIRECT/SINGLE responses are not durably cached; retries
can repeat their work. A timeout never silently converts SINGLE into a workflow.

## Provider/worker semantics

| Failure | Graph behavior |
| --- | --- |
| 408, 429, 500, 502, 503, 504 | Retry up to three JobExecution attempts |
| Timeout, connection/transport failure, remote protocol failure | Same bounded retry policy |
| 400, 401, 403 | Terminal; no uncontrolled retry |
| Invalid JSON/envelope, invalid structured output, contract or Quality Gate violation | Terminal |
| Optional market/competitor/experiments failure | Continue where dependencies allow; COMPLETED_WITH_LIMITATIONS |
| Required POSITIONING/VIRTUAL_CMO failure | Fail/block graph; hard dependents do not execute |

One model HTTP attempt per graph JobExecution attempt × at most three attempts =
**at most three module-provider requests per Job**, independent of `HTTP_RETRIES`.
Backoff is 5/10 seconds. Source rejection may consume an attempt without a model call.
Intent interpretation and owned-site extraction are separate pre-run single-attempt
calls; they are not part of the graph's per-Job budget. Owned-site confirmation
reacquires/extracts the snapshot. A changed snapshot requires fresh confirmation.

Workers never hold a DB transaction during provider execution. SIGTERM cancels active
I/O and closes owned resources without marking a Job failed merely for shutdown.
After lease expiry a replacement may call the provider again, including when the
previous call returned before persistence. External execution is **at-least-once**,
not exactly-once. Fencing rejects stale completion; artifact, successful Job and
dependent scheduling commit atomically. Exhausted attempts terminate safely.

Read-only polling uses one REPEATABLE READ snapshot. It never claims Jobs, wakes
workers or invokes providers. Readers can see the state before or after a node
commit, never a successful Job without its accepted artifact. Two lanes can run
independent optional research concurrently; POSITIONING waits for all optional
contributors to become terminal. Maximum topology is market + 3 competitors +
positioning + VIRTUAL_CMO + experiments = 7 nodes; minimum is the final 3 nodes,
with visible research-coverage limitations.

## Security and observability

`BOT_BACKEND_TOKEN` is a **service-to-service** credential, never a browser/public
client credential. Its holder can assert Telegram actors; do not distribute it to
end users. No OAuth redesign is included. An actor header alone cannot authenticate.
Unknown and foreign run reads both return 404; fixed runs are invisible to Copilot.

Correlate Telegram message/chat/actor via the bounded `tg:actor:chat:message` request
key, then API logs' run ID, then graph claim/finish logs' run ID and Job ID. Logs
contain result kind, status, duration and exception type. Source bodies, prompts,
provider responses, product_truth, confirmations and persisted context are forbidden.
Legacy text/image transport body logs and QC content/tracebacks have been removed.
Transport INFO/DEBUG URL logging is disabled in every process; framework exception
logging retains only exception type to prevent chained data/SQL parameters leaking.
Do not enable HTTP wire logging or dump environment variables in production.

## Deterministic verification and controlled live smoke

CI uses disposable PostgreSQL 15 and Redis 7, full `python -m pytest`, compilation,
`alembic check`, container build and fake-provider suites. Run the same tests locally
with disposable `MVP_TEST_DATABASE_URL`, `DURABLE_JOB_TEST_DATABASE_URL`,
`REDIS_TEST_URL`; never point test migration fixtures at production.

`scripts/check_copilot_release.py` uses `tests/compose.release.yaml` only in a guarded
`smm-mvp-ci-*` CI project. The fake Responses server pauses execution using an event:
the probe accepts a strategy with Redis already unavailable, observes one accepted
step and an active provider call, SIGTERMs worker/backend, recreates both, expires
only the disposable test lease, and verifies replacement/final presentation. It
also checks bot SIGTERM with fake Telegram transport and idle-worker shutdown.
The bot's real Dispatcher/signal lifecycle runs, but no Telegram network is contacted.
Never deploy the CI overlay, fake provider or fake bot transport to production.

Free operational smoke: `/health`, `/ready`, authenticated empty/list/status reads,
and invalid execute payload returning safe 422. These make no provider calls.
After deployment, an operator may explicitly perform **one controlled live request**
in the private bot: `Рассчитай лиды при бюджете 10000 и CPL 500`. Expect DIRECT_RESULT
with 20 leads, no graph Jobs; this uses one intent-model call and deterministic
calculation. It is a manual paid-capability smoke, never encoded into CI. A full live
strategy costs multiple model calls and requires a separate deliberate operator decision.

Manual recovery check: start a strategy with authorized minimal business context,
retain the request/run ID, restart bot, open `/copilot_runs`, select the run, and
inspect status plus final strategy/experiments/limitations. Also verify `/analyze`,
task/history and explicit image commands. Do not promise production throughput from
the fake-provider tests: 10 execute callers and 20 readers with a five-connection
pool establish a bounded correctness baseline only.

## Rollback

Stop bot ingress first and gracefully stop worker/backend. Restore the previously
recorded application images/code/configuration for all three services; keep the
PostgreSQL and shared image volumes. Do not run `docker compose down --volumes`,
delete runs/artifacts or manually mutate Job statuses. Task L has no schema change,
so no downgrade is needed. Preserve migration head `20260917_0009`.

The direct rollback target (merged PR #65) understands existing graph v1/v2 Jobs
and accepted artifacts. Its worker can reclaim leases after expiry. Its Telegram
bot lacks `/copilot_runs`; retain delivered status buttons/run IDs and use its
owner-scoped status endpoint while rollback is active. If rolling back further to
a version without graph execution, leave graph workers stopped and the runs intact
until a compatible worker is restored; do not redirect graphs into fixed workflows.
Restart PostgreSQL/Redis if needed, then backend/worker, check health, then bot.

## Retained components and future removal conditions

| Component | Still used by (code evidence) | Future removal condition |
| --- | --- | --- |
| AgentRunner | `app/services/task_pipeline.py`, `app/routers/agents.py` | Standalone task/agent APIs and saved task replay migrated with compatibility coverage |
| Fixed MarketingWorkflowService / MarketingExecutors | `app/routers/workflows.py`, `app/worker.py`, explicit `bot/handlers/workflow.py` commands and delivery | Existing fixed runs/deliveries drained or supported by a separately approved migration |
| ChatService marketing/chat behavior | `app/routers/chat_router.py`; CONVERSATION and legacy action callbacks in `bot/handlers/chat.py` | Conversation memory, follow-up and legacy action consumers migrated explicitly |
| Legacy image flow | Explicit bot image actions, `/images`, fixed creative executor | Separate feature/compatibility decision; Copilot has no image execution |

These are retention/removal candidates, not claims of dead code. No broad deletion
or new module, autonomous search, replanning, billing, admin UI or auth system is included.

## Release readiness evidence

See [Task L verification report](../development/production-hardening-release.md)
for the executed commands, counts, limitations and release matrix. Do not approve
the release with unresolved P1/P2 findings or an unverified container recovery gate.
