# POSITIONING Product Support Wire v2 release plan

This is an operator plan, not deployment authorization. Do not merge, deploy,
change production configuration, run user jobs, or replay failures as part of
preparing this PR.

## Contract and dependency

Merge Stage B [PR #126](https://github.com/Pickle-Pee/smm_ai_helper/pull/126)
before the rollout PR. The rollout branch starts at Stage B
`7280d316c922590cf2f14f6b6ef236d92f0c48cd`.

`POSITIONING_PRODUCT_SUPPORT_WIRE_ENABLED` defaults to `False`. False preserves
the v1 provider schema, prompt and result. True selects explicit product support
wire v2, independently of `POSITIONING_SCHEMA_PROJECTION_ENABLED`. Both backend
and graph worker use the production graph composition and must run the same
release with identical effective values for both flags.

Executor key `positioning.v1`, Registry `1.3.0` and persisted schema
`positioning.payload.v1` stay unchanged. V2 is validated and explicitly decoded
before existing server schema, semantic checks and Quality Gates. No v1 fallback
or extra model retry is introduced. Other executors are unchanged. This diff
requires no database migration; apply any separately required migrations from
the merged release using its existing release procedure.

## Phase A: merge Stage B

Confirm #126 is still the reviewed Stage B revision, required CI is green, and
its staging evidence remains applicable. Merge #126 only after release approval.
Record the resulting master SHA; do not merge unrelated old implementation
branches. Retain the supplied Stage B staging evidence as historical evidence,
not a new production or exact-head rollout test.

## Phase B: merge rollout

Retarget this dependent Draft PR from `codex/positioning-stage-b-integration` to
`master` after Stage B is present there. Inspect the resulting diff, especially
if Stage B was squash-merged, and ensure only rollout changes remain. Re-run
required CI for the resulting candidate: CI / python (compile, disposable DB
migrations/check, full tests) and CI / container-smoke. Check exact candidate SHA
and resolve conflicts without changing unrelated behavior. Mark ready and merge
only after review and passing required checks. Never merge directly from this
preparation task.

## Phase C: deploy with wire disabled

Record the previous image/revision and effective projection setting. Explicitly
set wire=False for backend and every worker; preserve projection's existing
value. Use the established ingress/drain deployment procedure in
`worker-drain-control.md`. Drain synchronous API requests as well as worker
attempts before replacing processes. Confirm every instance uses the same
release/configuration before resuming ingress. Keep wire=False through initial
health and existing telemetry checks. Do not run production test jobs as part of
this preparation.

## Phase D: controlled activation

The wire policy is captured when each process builds its executor registry;
jobs do not persist a wire policy. A worker pause alone is insufficient: it
allows pending jobs and descendants, so a paused/drained attempt population
can still contain unfinished graphs.

1. Block new user work and continuations at every ingress, including synchronous
   Copilot execution, and drain in-flight API requests. Inventory all API and
   worker instances and other writers.
2. While wire=False, let already admitted work finish normally, including queued,
   deferred and downstream graph jobs. Verify no unfinished graphs/jobs remain
   that could later execute POSITIONING. Do not replay terminal failed jobs.
   If waiting work cannot finish, postpone activation; do not silently transfer
   it to a different contract or force-clear its claims.
3. Pause worker claim admission using the existing epoch-checked operator
   procedure; require fresh drained status for both lanes and separately prove
   the relevant nonterminal backlog is empty. Retain the admission/ingress barrier.
4. Set wire=True identically for backend and all workers. Preserve projection's
   value. Recreate processes under the barrier; verify image SHA and effective
   boolean settings on every instance. Do not log credentials or raw env files.
5. Recheck drain and backlog evidence, then resume workers and open ingress in
   the agreed order. Only newly admitted work may use v2. Any controlled live
   canary/provider call requires separate production authorization and budget.

## Phase E: monitoring and rollback

Compare a recorded v1 baseline with v2 over a predefined initial observation
window and volume. Observe POSITIONING schema/semantic rejection stages, wire
version/schema hashes, accepted product claims/Quality Gate decisions, provider
errors/incompletes, latency, timeouts, queue lag and job failure rates. Correlate
request/execution IDs without collecting raw user content. Stop expansion for
any backend/worker policy mismatch, invalid persisted shape, unexpected retries,
or a material regression in acceptance/errors/latency against the agreed baseline.

For rollback, close ingress and drain in-flight API requests. Let v2 work finish
under v2, and apply the same empty-backlog and paused-worker barrier before
recreating all backend/worker processes with wire=False. New work then uses v1;
stored artifacts remain unchanged. Keep projection unchanged and do not replay
old failed work. A flag change does not update an already running process.

If v2 work cannot finish safely, keep ingress/claims closed and escalate for an
explicit per-job disposition. Do not claim rollback is safe while silently
allowing unfinished v2 jobs to resume under v1. Retain the wire-capable release
for flag rollback; reverting to an older image requires the same drain barrier
and a separate compatibility check. Do not delete or rewrite persisted artifacts,
tokens, leases or attempt markers.

## Validation evidence

The rollout test matrix covers all four wire/projection combinations, default
and explicit-off equivalence, environment parsing, API/worker registry wiring,
unchanged persisted shape, and unchanged requests/results in five other modules.
Neighboring offline suites cover POSITIONING v1/v2, malformed support, seed
variants, registries, composition, graph/model boundaries, and Quality Gates.
Exact-head local test totals and GitHub Actions evidence are recorded in the PR.
