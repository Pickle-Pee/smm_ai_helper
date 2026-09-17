# Durable module graph runtime

`app/orchestration_runtime/` is an internal application boundary. It is not used
by HTTP routers, Telegram, Copilot execution or `python -m app.worker`.
Production composition is a separate integration gate.

## Planning, compilation and execution

Planning still uses metadata-only Registry 1.0.0. `OrchestrationPlan` and
`PlanNode` have no execution state and remain `PLANNING_ONLY`.
`competitive_positioning_v1` is the first executable vertical after explicit
compilation: `competitor_analysis -> positioning`. Competitor analysis receives
scoped competitor source/business facts; positioning requires product, target,
customer job, alternative and product truth, plus accepted predecessor results.
Copilot's comparative positioning policy only proposes this scenario.
`MARKETING_STRATEGY -> strategy_builder_v1` is unchanged.

`new_positioning_v1` is unchanged: market and competitor analysis both precede
positioning. MARKET_ANALYSIS has no binding in Registry 1.1.0, so compilation
rejects the whole plan. No node/dependency is removed or substituted.

The pure `PlanCompiler(ModuleRegistry.load("1.1.0"), executors)` checks source
validation, exact descriptor compatibility, graph structure, runtime-safe node
IDs, output membership and registered executor/module/contract coherence.
Unknown scenarios, blocked plans, metadata-only modules and inline SECRET or
unauthorized facts fail before persistence. PUBLIC and INTERNAL facts may persist.
Secret references are not supported.

`CompiledExecutionPlan` is frozen and contains `schema_version` =
`compiled_execution_plan.v1`, `source_plan_id`, `scenario_key`, `registry_version`,
ordered `nodes`, `dependencies`, and a SHA-256 `execution_fingerprint` over the
canonical JSON document excluding the fingerprint itself. Each frozen node has
`node_id`, `module_id`, `objective`, `expected_outputs`, `context_packet`,
`dependency_node_ids`, and declarative `binding` (including compatibility evidence).
No Python implementation is serialized. Limits are 32 nodes, 24 levels and 1 MiB
per serialized document, signed 64-bit JSON integers and finite numbers.

## Storage and identity

Additive migration `20260917_0009`, parent `20260909_0008`, adds
`orchestration_plans`. Its composite primary key is `(run_id, revision)`.
Source identity and compiled fingerprint are separately unique within a run;
a partial unique index allows at most one active revision. Revision must be
positive. Source ID, Registry version, fingerprint and JSON must agree on read.
The service never updates a compiled document; direct SQL mutation is unsupported
and fingerprint/shape mismatches fail closed. This is application immutability,
not a tamper-proof database or a database UPDATE prohibition.

The table supports future revisions; this runtime creates and accepts only active
revision 1. Replanning and revision switching are deliberately unimplemented.
No mutable WorkflowNode table is needed: nodes without ready dependencies have no
Job. Existing `MarketingRun` owns the graph, with workflow type
`orchestration_graph.v1` and statuses `queued`, `running`, `blocked`, `completed`,
`failed`. `state_json` contains only safe terminal failure metadata, not the plan.

`start_compiled_run(owner_id=..., run_id=..., plan=...)` requires an existing,
caller-authorized User ID and explicit run identity. It revalidates the compiled
plan and available executors before opening a session. Concurrent identical
starts replay; a different owner, workflow or plan under the same ID is rejected.
This is an internal trusted-caller operation, not an authorization endpoint.

Each ready node maps to one `orchestration.module` Job. Job IDs hash a
length-safe canonical `(workflow type, run, revision, node)` identity to the
existing 32-hex storage contract; a primary-key conflict fails closed. Payload
`module_job.v1` contains routing metadata only: run, revision, fingerprint, node,
module, executor key and Registry version. Node IDs must fit the existing
64-character workflow_step grammar; there is no truncation.

Artifact identity is `(run_id, p<revision>.<node_id>)`, fitting String(128).
`module_artifact.v1` contains run/revision/node/module identity, full
`execution_result`, and `module_quality.v1` evaluation metadata: batch identity,
fingerprint, accepted result IDs and accepted claim IDs. Job.result_json anchors
the artifact fingerprint and key. Strict JSON codecs restore typed enums,
timestamps, frozen payload, claims, evidence, assumptions and limitations.
Unknown fields, invalid shapes or unsupported versions fail closed.

## Durability, gates and fencing

Existing fixed invariants are retained: PostgreSQL is authoritative; Redis is an
expendable wakeup; Job lifecycle remains pending -> running -> succeeded/failed
with versions 0/1/2; attempts, retry availability, token and lease live separately
in JobExecution. No transaction spans executor/model/site I/O.

The graph service owns its short transactions. All mutations acquire locks in
run -> execution lease -> Job order. Claims use `FOR UPDATE SKIP LOCKED`, a fresh
token and a 330-second default lease; the worker's default 300-second execution
timeout must be shorter. Attempts default to three; transient timeout/network
and HTTP 408/429/500/502/503/504 failures retry after 5/10 seconds. The Job remains
running during retry. Crashed attempts consume the same bounded budget.

`load_work` restores the exact plan and accepted ancestor artifacts from SQL,
checks routing and quality acceptance, then closes its transaction. The worker
dispatches the injected executor once and evaluates current plus accepted
ancestor normalized results outside persistence. The existing Quality Gates
evaluator intentionally uses metadata-only Registry 1.0.0, whose descriptor
metadata matches the execution Registry. Neither executor nor dispatcher owns
the evaluator. Completion rechecks acceptance and identity under the run lock.

A result absent from `synthesis_manifest.accepted_result_ids` is terminal
quality failure and cannot become an accepted artifact. BLOCKED is a domain
outcome: Job fails, run becomes blocked, and bounded enum reasons are stored.
Other errors persist only stable error codes, never exception text, provider
responses, or chain-of-thought. SQLAlchemy persistence failures propagate and
leave the committed claim recoverable.

Successful completion atomically writes the artifact, completes Job, clears the
lease and calls the same locked advance operation used by public-internal
`advance(run_id)`. This deliberately closes the crash window between completion
and scheduling. Run locking, deterministic IDs and database uniqueness prevent
duplicate jobs/artifacts. Concurrent advance is idempotent. Wakeups happen only
after commit and failure to publish cannot undo a durable Job.

An expired or replaced token cannot finish/fail a node or advance through a
completion. Restart reconstructs full upstream execution results from artifacts;
the service/worker/executor instances retain no graph progress. DB scanning can
claim pending or expired jobs without any Redis hint.

## Verification and limits

`tests/test_graph_compiler.py`, `test_graph_postgresql.py`, and
`test_graph_migration.py` exercise strict contracts, the real planner/compiler/
dispatcher/executors with fake model/site capabilities, restart, stale claims,
concurrent scheduling, Redis loss, blocked/quality/malformed/provider failures,
corrupt persistence, duplicate starts, SQL rollback/recovery and migration
upgrade/downgrade/re-upgrade with existing fixed-run preservation.

For manual internal verification, create a User in a disposable migrated database,
compile a validated competitive positioning plan with explicit injected
capabilities, start the run and call `ModuleGraphWorker(service).once()` twice.
After the first call recreate the entire composition. Expect two succeeded Jobs,
two accepted artifacts, a completed run, and zero WorkflowDelivery rows.

Fixed `MarketingWorkflowService`, production worker main, standalone tasks,
public DTOs and delivery remain unchanged. There is no public ingress, generic
synthesis, replanning, resume/clarification, MARKET_ANALYSIS implementation or
automatic production traffic. External model/site calls can repeat after lease
expiry; exactly-once external effects are not promised. Quality Gates validate
structured provenance, not semantic truth. Result/body size limits and the
allowlisted scenarios bound this first runtime; arbitrary large graphs and
multi-revision execution require a future compatibility design.

### Verification evidence (2026-09-17)

Base: `07098800820abe78f4c52772c78310790fc6b28d` (merged PR #57).
Local disposable PostgreSQL 15 and Redis 7 were used with fake model/site
capabilities; no live provider or Telegram polling calls were made.

- Focused planner/compiler/graph/migrations/execution/Registry/Quality Gates/
  Copilot/fixed workflow suite: **780 passed**. Four additional compiler and
  architecture regression cases were subsequently included in the full suite.
- Full `python -m pytest -q` in the built Linux Python 3.11 image with separate
  disposable Job and MVP databases and Redis: **1107 passed, zero skips**.
- Built-image graph/fixed PostgreSQL/provider-protocol/Redis smoke: **46 passed**.
- `scripts/check_container_persistence.py seed`, backend/worker force-recreation,
  then `verify`: both passed (run, shared image bytes and owner checks).
- `python -m compileall app bot`, `git diff --check`, `alembic upgrade head`,
  `alembic check`: passed. The new migration round-trip test executes upgrade from
  parent, downgrade one revision, re-upgrade and schema comparison, preserving
  an existing fixed workflow run.
- Review checked run/lease/Job lock ordering, atomic completion plus advance,
  stale-token fencing, strict persistence boundaries, exact executor routing,
  safe failure codes, no production ingress and no unrelated fixed changes.

An earlier Windows full-suite attempt exposed an old architecture allowlist
(updated to admit only the graph service) and an existing standalone 0.2-second
timeout test that expired before its model double was entered. Standalone code
and that test were not changed; the full target Linux run passed, including it.
