# Release admission and drain

This procedure applies when the running backend and bot both support release
draining. Use one Uvicorn process per backend container. Inventory every
backend instance, the Telegram poller, worker lanes, and direct database
writers before the window.

Mount an operator-owned directory read-only in every backend. Set
`RELEASE_BARRIER_STATE_FILE` to a file in that directory. Set
`RELEASE_BARRIER_TOKEN` in the backend and bot to the same separate random
secret of at least 32 bytes. Keep it out of public ingress, client code, access
logs, and command arguments. The public edge must reject `/internal` and
strip the release header. An unset file setting preserves normal operation
for deployments that do not use this procedure.

Replace the state file atomically within the mounted directory. The exact
values are `open`, `bot-only` and `closed`, each followed by one newline.
A missing, malformed or unreadable file closes admission. Mount the
directory so file replacement is visible to running containers.

1. Confirm `open` through `GET /internal/release/barrier` on each backend.
   Supply `X-Release-Barrier-Token` using protected runtime configuration.
   Record the backend container identity and reported PID. The in-flight
   count applies to that process.
2. Enable maintenance at the public edge and change the file to
   `bot-only`. Confirm retryable 503 from public and direct HTTP paths,
   including a caller inside Compose without the release token. The bot
   keeps access to finish accepted updates and to acknowledge delivery.
3. Stop the bot with SIGTERM and an unlimited Docker stop timeout
   (`docker stop --time -1`), under operator observation. Polling stops
   first. Accepted update tasks finish and the current delivery attempt
   returns before the Telegram session closes. Require exit 0 and a fresh
   `event=telegram_release_drained` log from that process. Keep the window
   closed if the wait exceeds its budget. An interrupted Telegram send or
   ambiguous ack remains subject to the durable delivery lease.
4. Change the file to `closed`. Confirm 503 for non-health traffic even
   with bot credentials. Require `closed` and `in_flight: 0` from every
   inventoried backend process before replacement. Keep direct database
   writers quiescent. Health and readiness remain available during
   maintenance.
5. Apply [Worker Drain Control](worker-drain-control.md). Require the
   paused epoch, zero outstanding attempts and zero active leases in both
   lanes. Keep pending and deferred jobs in PostgreSQL. Hold ingress and
   worker admission closed through migration and image replacement.
6. Check the new backend, persistent state, exact images and schema.
   Confirm the new backend still reports `closed`. Confirm worker status
   at the same epoch and resume admission. Open backend admission, then
   start the single bot poller and lift the public maintenance response
   after health and delivery checks.

If an intermediate gate fails, keep the latest proven fence in place. Before
replacement, the original images can resume after the same epoch is verified
and the bot has exited cleanly. For rollback to an image without the barrier,
maintain a separate edge and network fence until the legacy backend and
worker pass checks on the current schema. A rollback does not downgrade
Alembic. Recovery after an ambiguous provider call or Telegram send follows
the existing durable execution and delivery contracts.

The first transition from an older bot that cancels its accepted update tasks
needs independent evidence that the old poller and delivery loop are
quiescent before it is stopped. Installing this code only in the incoming
image cannot supply that evidence.
