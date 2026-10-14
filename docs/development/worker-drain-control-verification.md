# Worker Drain Control verification

Date: 2026-10-14. Base: `f964237` (`master`, merged #122). No production connection,
deployment, production migration or paid provider invocation was performed.

## Architecture and implementation plan

1. Trace the two authoritative claim boundaries, producers and lease lifecycle.
   Keep durable producers and independent `/chat`/`/tasks` operations available.
2. Serialize both claims against one PostgreSQL admission row, using SHARE locks
   inside claim transactions and UPDATE locks for operator pause/resume. Track
   individual attempts durably so lease replacement cannot hide earlier I/O.
3. Expose a protected operator CLI with aggregate JSON, epoch checks and a live
   drained predicate. Preserve provider execution, artifact fencing and retries.
4. Prove concurrency/recovery with PostgreSQL and provider fakes, independently
   review the diff, and update deployment evidence and legacy bootstrap contracts.

## Executed local checks

Disposable PostgreSQL 15.19 on loopback, separate Redis on loopback, Python 3.12.14.
The new migration was validated on a fresh database after the final schema change.

| Check | Result |
| --- | --- |
| `python -m alembic upgrade head` | Passed, fresh DB through `20261014_0012` |
| `python -m alembic check` | Passed, no model/schema differences |
| New revision downgrade to `20261006_0011` and upgrade head | Passed in lifecycle suite |
| New PostgreSQL drain integration suite | 19 passed, 17.37 seconds |
| Final combined relevant suite below | 207 passed, 70.89 seconds |
| Offline CLI, graph-worker, model-adapter and provider telemetry tests | 133 passed, 3.24 seconds |
| Independent reviewer: CLI + graph-worker tests | 65 passed |
| `git diff --check` | Passed |

Final combined command, with `MVP_TEST_DATABASE_URL` and `REDIS_TEST_URL` pointing
only to disposable local stores:

```text
python -m pytest -q --basetemp=.local-test/drain/markers-relevant
  tests/test_worker_drain_postgresql.py
  tests/test_worker_drain_lifecycle_postgresql.py
  tests/test_worker_control.py
  tests/test_production_worker_postgresql.py
  tests/test_production_graph_worker.py
  tests/test_marketing_mvp_postgresql.py
  tests/test_graph_postgresql.py
  tests/test_provider_request_telemetry.py
  tests/test_workflow_redis.py
  tests/test_task_finalization_postgresql.py
```

Existing Pydantic, Alembic configuration and UTC datetime deprecation warnings
remain. No tests in that combined run were skipped.

## Evidence coverage and independent review

PostgreSQL lock-wait observations prove both orderings of pause versus claim,
both lane families, concurrent service instances, persisted pause after restart,
pending/deferred recovery and epoch fencing. Held OpenAI MockTransport calls finish
while paused, and accepted artifacts remain unique. Real loopback connection
failure and missing control-row tests prove admission fails closed. Restricted
PostgreSQL roles prove workers can lock admission and insert/delete their markers
without permission to reopen admission; operator status uses only metadata grants.

Independent review found that counting only the current JobExecution token misses
a superseded attempt after a wall-clock lease jump. Durable per-attempt markers
resolve this: both-lane regressions hold the first provider fake, finish its
replacement, and require drain to stay blocked until the fenced original unwinds.
Another regression proves cleanup cannot remove another attempt's marker.
The review's marker column-SELECT grant finding was also fixed and tested.
Independent re-review reported no remaining material findings.

Local lifecycle tests invoke the installed SIGTERM callback after a real drain,
then restart the worker with pending graph work and verify pause/count preservation.
The updated CI `scripts/check_worker_lanes.py` additionally sends actual container
OS SIGTERM after a live gate and verifies persisted pause after restart. Docker is
unavailable on this Windows host; that actual-container result must be taken from
the PR's CI, not inferred from local callback tests.

## Operational limits

The [deployment contract](../operations/telemetry122-worker-deployment-plan.md)
uses a live CLI check bound to the operator's epoch. Pending/deferred jobs are
retained work, not provider-I/O evidence. A crash or failed marker cleanup can
conservatively block drain; the CLI has no forced-clear operation. Separate
independently proven recovery is required before treating those leftovers as safe.

The first production installation remains **NO-GO** until an external maintenance
barrier covers every producer listener, accepted producer handlers have finished,
the legacy backlog is drained and every legacy worker is proven stopped. An old
worker ignores the new row. Neither these tests nor a saved JSON file proves that
production bootstrap. See the [bootstrap plan](../operations/worker-drain-control.md#first-rollout-legacy-bootstrap).
