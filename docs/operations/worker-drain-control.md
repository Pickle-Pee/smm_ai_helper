# Worker Drain Control

First #122/#123 installation: use the consolidated
[first-production-rollout runbook](first-production-rollout.md), including its
read-only collector and explicit NO-GO evidence gaps. It is prepared for review,
not authorization for production access or cutover.

Worker Drain Control closes **claim admission**, while API and Telegram continue
to save durable work in PostgreSQL. It covers the fixed `marketing.step` and graph
`orchestration.module` lane families across all compatible worker instances using
the same database. It does not pause `/chat`, `/tasks`, images, synchronous Copilot
modules, intent interpretation, or Telegram delivery.

This is an operator procedure, not a deployment authorization or an installer.
No production access is needed to implement or test the control. The first rollout
has a separate [legacy bootstrap gate](#first-rollout-legacy-bootstrap).

## Authoritative boundary and lifecycle

| Producer | Worker-owned work |
| --- | --- |
| `POST /workflows` → `MarketingWorkflowService.start` | `_enqueue` creates `marketing.step` analysis when business context is complete |
| `PATCH /workflows/{run_id}/context` → `.context` | `_enqueue` creates analysis when missing context becomes complete |
| `POST /workflows/{run_id}/continue` → `.continue_run` | `_enqueue` creates creative or mentor after the saved predecessor exists |
| `POST /copilot/execute` → `MarketingCopilotService` WORKFLOW path → `GraphExecutionService.start_compiled_run` | `_advance_locked` creates initial `orchestration.module` jobs |
| Graph `.advance`, accepted `.finish`, optional terminal `.fail` | `_advance_locked` creates dependency-ready descendant graph jobs |
| Fixed/graph retryable `.fail` | Existing JobExecution becomes deferred with the existing 5/10 second backoff; no new attempt is claimed while paused |
| Telegram free text, Copilot continuations, explicit `/analyze` and workflow continuation callbacks | Call the HTTP paths above; they do not claim work themselves |

The repository has one JobPersistenceService creation boundary per lane family:
fixed `_enqueue` and graph `_advance_locked`. Generic persistence callers do not
execute a worker attempt until one of the two authoritative `.claim()` methods
accepts it. Direct or out-of-repository executors that bypass those methods are
outside this guarantee and must be excluded by process inventory before rollout.

`/workflows/profile`, workflow reads, `/workflows/{run_id}/delivery/retry`, and
`/internal/delivery/*` do not create either worker job kind. Delivery retries update
WorkflowDelivery independently. `/chat`, standalone `/tasks`, `/images` and the
deprecated agent API do not create these two job kinds. Their synchronous provider
I/O must not be confused with worker activity or blocked for a worker-only update.

PostgreSQL owns Job/JobExecution state, retries, leases, fencing, accepted artifacts
and the drain latch/attempt markers. Redis carries hints only. Both due scans and hinted claims
pass through the same control. A lost or consumed hint during pause cannot lose a
Job; due scans recover it after resume.

## Durable control contract

A new migration `20261014_0012` creates a singleton `workers` row in
`worker_admission`, initially open to preserve
existing startup behavior, plus durable `worker_attempts` markers keyed by
`(job_id, claim_token)`. Both claim methods take a shared row lock before any
claim mutation and retain it until their short transaction commits. Pause/resume
take an exclusive lock on that row. Consequently, a pause acknowledgement comes
after earlier claim transactions and prevents every later compatible claim from
issuing work. A claim that won the race belongs to the drain population.

The row stores the admission state and a monotonic epoch. State transitions advance
the epoch; conditional operator commands reject a stale expected epoch. A missing
row, missing migration or database error fails closed; no process-local cache or
automatic open fallback admits work. Restart reads the same durable state.

Pause does not cancel an active attempt, alter its timeout, clear its token, expire
its lease, change its attempts counter, or rewrite Job/run/artifact state. Active
attempts run through their normal finish/fail transaction. They can schedule
descendants or defer retries while paused. Those jobs remain durable, waiting for
resume. No DB transaction or drain lock spans provider I/O. Existing provider
timeouts and fencing can still reject a stale result; drain does not promise
exactly-once external calls or repair an earlier crash.

Every admitted attempt creates its marker atomically with its claim. The worker
removes only that attempt's marker after its provider work has unwound, including
fenced or superseded attempts. A lease reclaim can replace the current
JobExecution token while an older provider call is still running (for example,
after a clock jump). The older marker remains until that older call unwinds, so
the replacement's successful completion cannot make status falsely drained.
Markers do not change retry ownership, lease expiry or artifact fencing.

A process crash or failed marker cleanup leaves conservative evidence behind.
SIGTERM cancellation can remove a marker after cancellation unwinds provider I/O;
its current JobExecution token remains available for existing recovery and still
blocks drain. The CLI never force-clears either token or marker.

## Operator interface and evidence

Run `python -m app.worker_control pause|status|resume` from a reviewed compatible
release with an explicit
`WORKER_DRAIN_DATABASE_URL`. Supply the connection through the protected operator
environment, never a CLI argument or committed file. There is no public HTTP
endpoint and no implicit fallback to application credentials. Restrict the
operator host/account and PostgreSQL credentials. PostgreSQL `FOR SHARE` and
`FOR UPDATE` need UPDATE privilege on at least one column even when no value is
changed. Workers therefore need `SELECT` plus `UPDATE(id)` on `worker_admission`
for row locking; only the operator role gets `UPDATE(paused, epoch)`. Status uses
the same control row lock and needs that permission plus SELECT on the relevant
Job/JobExecution metadata columns and `worker_attempts(job_id, claim_token)`.
Workers need SELECT(job_id, claim_token), INSERT and DELETE on `worker_attempts`;
their runtime removes the exact
marker for the attempt it owns. Keep payload columns outside operator grants.
The dedicated URL must use the `postgresql+asyncpg` driver. Keep migration ownership
separate. A command failure prints a bounded error and returns nonzero; do not
print settings, connection exceptions or SQL parameters.

Command sequence:

1. Read status and capture the epoch.
2. `python -m app.worker_control pause --expect-epoch N`; require a successful
   committed response and save its
   resulting epoch E. A lost acknowledgement is uncertain: read status again,
   rather than assuming pause failed or admission is open.
3. Repeat `python -m app.worker_control status --require-drained --expect-epoch E`.
   Exit 0 is a successful live gate. Exit 2 is WAIT/STOP,
   never permission to signal a worker. Retry at a bounded operational interval.
4. Once the live check passes, retain pause and E through worker replacement and
   startup verification. Recheck immediately before stopping each instance.
5. Run a final live status gate, then explicitly
   `python -m app.worker_control resume --expect-epoch E`. Confirm the resulting
   open epoch; PostgreSQL due
   scans will claim pending and deferred work when eligible.

The safe JSON contract is `schema_version=worker_drain.v1`, server `observed_at`,
integer `epoch`, `admission` (`paused`/`open`), boolean `drained`, and `lanes.fixed`
and `lanes.graph`, each with these aggregate counts:

| Field | Meaning and cutover interpretation |
| --- | --- |
| `outstanding_attempts` | Distinct `(job_id, claim_token)` union of durable worker_attempts markers and current non-null JobExecution tokens, **including expired and superseded attempts**. Must be zero in both lanes |
| `active_leases` | Unexpired JobExecution leases. Must be zero in both lanes; zero alone is insufficient |
| `pending_jobs` | Retained unfinished unclaimed work. May be nonzero during a successful drain |
| `deferred_jobs` | Subset of pending_jobs with future availability, including deferred retries. May be nonzero |

`drained` requires paused admission and zero outstanding attempts in both families.
Pending-job/run counters and Redis hints do not establish active LLM calls;
outstanding attempt markers/tokens are the conservative execution evidence.
A file containing these fields is an audit record only:
it cannot prove current admission, database identity, compatible worker code, or
the absence of legacy executors. Use the **live** CLI gate with E against the same
PostgreSQL database used by every worker. Do not reopen admission concurrently;
the operator owns the pause window. Epoch checks detect an intervening resume even
if another pause returns the state to paused.

If an expired token or a retained attempt marker remains, status deliberately stays
undrained even when provider I/O appears idle. Expiry or supersession cannot prove
I/O ended. A crash or DB cleanup failure may retain a marker after the actual call
has ended; investigate and independently prove that attempt/process can no longer
perform provider work before any separately authorized recovery. Do not clear
tokens/markers or rewrite leases for deployment. The drain CLI has no forced-clear
command. Keep the update blocked until independently proven recovery is complete.
DB outage also blocks evidence; recover the database before cutover.

SIGTERM retains its existing immediate cancellation semantics. Send it only after
the live drained gate passes. An active-worker SIGTERM, SIGKILL, Docker timeout or
container pause is not a substitute for drain.

## First rollout: legacy bootstrap

**NO-GO until independently verified external maintenance evidence exists.** The
old production worker does not read this row. Creating it or closing it with new
code cannot bar an old claim. A new status response, two empty job snapshots, log
silence, or a manually filled `barrier.json` does not change that fact.

A realistic one-time bootstrap must first establish an external ingress barrier
for exactly the job-producing HTTP paths in the table, across **all** public and
internal listeners/callers. The smallest possible mechanism is a controlled proxy
maintenance rule for `/copilot/execute` and the three mutating workflow routes,
with network policy preventing backend bypass by Telegram/internal clients and
direct callers. The HTTP rule may conservatively cover synchronous Copilot execute
branches for this one window. Independent `/chat`, `/tasks`, reads and delivery
can stay available when routing permits it. Return a retryable maintenance response
and preserve Telegram update/idempotency recovery; abruptly killing bot handlers
does not prove their already accepted backend requests ended.

Before using that mechanism, verify that the deployment actually routes **every**
producer through it. This repository does not supply such a proxy topology or an
accepted-request counter. If internal Compose traffic bypasses the proxy, the rule
alone is insufficient. An alternative is graceful request draining of every API
producer instance behind a held external barrier, with an independently monitored
zero accepted/in-flight handler count. This temporarily limits the backend and
needs a separately approved maintenance window. A waiting pre-run OpenAI request
can create its graph job after an apparently idle DB snapshot, so waiting only for
jobs or proxy connection silence is insufficient.

After ingress is closed and all already accepted producers/transactions are proven
finished, leave legacy workers running until **all** fixed/graph pending/running
jobs (including future retries), dependency-ready descendants and outstanding
tokens have drained. Retain the prior #122 metadata-anomaly checks for missing
run/JobExecution state; zero counts that exclude malformed rows are not legacy
drain evidence. Inventory all worker instances and direct writers; capture
unchanged process/image identities alongside repeated DB observations. Then stop
the idle legacy workers and prove none remains/restarts. Apply the new migration
and pause the row before starting any compatible worker. Start the new workers
paused, pass the live status gate, verify actual image sources and both lane
startup, and only then resume and reopen ingress in the agreed order.

If a legacy attempt is stuck, a producer cannot be accounted for, or ingress cannot
be closed and observed reliably, keep **NO-GO** and retain the old worker. There is
no safe forced bootstrap hidden in this feature. Migration downgrade and rollback
to any pre-control worker require the same external barrier, because those workers
ignore durable pause. Never use a control-aware release's status as evidence for a
legacy rollback target.

## Verification boundary

Disposable PostgreSQL integration/concurrency tests establish database lock order,
multi-instance admission, persisted pause, normal attempt completion, deferred
retry/pending recovery, superseded attempts still performing provider I/O,
DB failure, artifacts and idle SIGTERM with fake providers.
They do not establish the production process inventory, proxy barrier, database
credentials, image identity, operator exclusivity, or a live production drain.
Those remain explicit operational gates; no paid model call is required to check
admission or status.
