# Responses retry policy

## Scope and rollout contract

`RESPONSES_WORKFLOW_GOVERNANCE_ENABLED` defaults to false. It opts newly created
durable graph runs into governance; it does not reinterpret old runs or change
compiled plans, provider schemas, executor business validation, Quality Gates or
public DTOs. The safe flag is necessary because the previous durable contract
allowed replacement workers to retry an unknown external outcome after expiry.

At run creation, the service snapshots `input_json.responses_retry`: policy
version, maximum calls, maximum cumulative requested output tokens and the bounded
call receipts. The call cap is three times the number of compiled nodes; the
aggregate RESPONSES_WORKFLOW_MAX_OUTPUT_TOKENS allowance defaults to 192,000. These persisted limits survive
worker restart and later configuration changes. Missing policy markers retain
legacy behavior. Coverage and terminal failure state_json rewrites do not erase
the governor because its metadata belongs to input_json.

Existing governed runs remain governed when the flag is switched off; the flag
controls enrollment, not enforcement. No database migration is necessary. Only
trusted service code writes this internal metadata; users cannot supply it through
HTTP inputs. Direct SQL edits are unsupported.

## One owner and one send boundary

The durable graph workflow owns retry decisions. The transport performs one POST
per invocation in governed graph context, even if a nested caller asks for legacy
mode. It uses the existing task-local telemetry context and injected reservation /
completion callbacks to the graph service. A graph executor cannot obtain a local
three-send loop inside a durable attempt.

Before every POST, the service validates the current run, Job routing, claim token
and unexpired lease using the same active-ownership check as completion, then:

1. Rejects another call on that node after an unresolved/unknown or successful prior call.
2. Checks the per-node three-call bound, run call cap and cumulative output cap.
3. Adds a reserved receipt containing safe correlation and requested allowance.
4. Commits the short transaction before starting HTTP I/O.

The transport reports the result to the service through a second short fenced
transaction. Raw request/response content and exception text are never receipts.
Known failures count against the same cap as successes. Requested output allowance
is never refunded merely because reported usage is zero or a request failed.
Output allowance bounds request parameters, not actual cost: it excludes input
cost and cannot account for charges hidden by a lost response.

A successfully observed provider response also blocks a subsequent resend if the
worker crashes before artifact persistence: a provider success receipt is not an
accepted module artifact, but repeating it could pay twice.

A provider_call_id denotes one local reserved send, graph_attempt_id denotes one
claim, and module_execution_id denotes the stable node execution. They must not
be merged into one identifier. Concurrent nodes share the run lock while reserving,
so aggregate limits cannot be overdrawn through parallel commits.

## Decision table

| Observed condition | Governed decision | Legacy graph behavior |
| --- | --- | --- |
| HTTP 429/500/502/503/504 response | Workflow may defer retry within all caps | Deferred retry within three claims |
| incomplete_empty_max_output_tokens with explicit zero output/reasoning | Workflow may defer retry within all caps | Deferred retry within three claims |
| Other incomplete / refusal / malformed envelope | Terminal rejection | Terminal rejection |
| Executor validation / Quality Gate rejection | Terminal existing failure | Terminal existing failure |
| HTTP 408 | Unknown outcome: stop, do not resend automatically | Deferred retry |
| Timeout after sending / transport loss | Unknown outcome: stop, do not resend automatically | Deferred retry |
| Cancellation | Propagate cancellation; reserved outcome blocks later resend | Replacement may resend after lease expiry |
| Worker crash / missing completion receipt | Reserved outcome is conservatively unknown; replacement cannot resend node | Replacement may resend after lease expiry |
| Lease expired or fencing token replaced | Stale owner cannot reserve or persist completion | Existing fencing retained |
| Attempt / call / allowance cap exhausted | Predictable terminal failure; no further POST | Three-claim exhaustion remains terminal |
| Persistence unavailable before reservation commit | No POST admitted | Existing worker leaves lease recoverable |
| Persistence unavailable after provider response | Receipt may remain reserved; stop rather than assume success | Replacement may resend |

The decision to stop after an unknown outcome is the workflow owner's explicit
policy. There is no new automatic recovery or manual replay endpoint for uncertain
calls. An operator can inspect provider records using safe IDs, then follow the
existing product flow for a deliberately new request. That creates new work and
may incur additional charges; it is not proof that the earlier attempt was free.

Terminal governance failures retain the existing execution_invalid public failure
code. The internal last_retry_decision stores the bounded policy reason in the
persisted run policy; it is not a new public error contract.

Known retryable failures use existing deferred backoff (5s, then 10s with three
claims). A retry is queued in PostgreSQL; Redis wakeups remain expendable. Job
lifecycle is unchanged: pending -> running -> succeeded/failed. Strategy research
and EXPERIMENTS nodes are optional; POSITIONING and VIRTUAL_CMO
are required. Optional failure can yield completed_with_limitations; a required
node failure stops the graph. Acceptance and dependency barriers are unchanged.

## Restart, fencing and conservative gaps

A crash before reservation leaves no provider receipt, so a replacement may retry
within the durable claim budget. A reservation is a durable permission to try
sending, not proof that HTTP started.
A crash after its commit but before POST can stop work that never reached the
provider. This is intentional: the replacement cannot distinguish that case from
provider acceptance followed by process death. No transaction spans provider I/O.

A late response cannot authorize a stale worker to finish a Job. If the lease
expires before receipt persistence, the reserved record stays uncertain, and a
replacement stops the node. Cancellation cannot roll back an already sent request
at the provider. These guarantees prevent local automatic resends after unknown
outcomes; they do not promise exactly-once provider execution or absence of real
charges. Offline tests demonstrate send counts and state transitions only.

## Operational compatibility and rollback

This document is a rollout procedure, not authorization to deploy this PR.

1. Keep the flag disabled while validating telemetry and offline regression tests.
2. Before enabling enrollment, pause claims with the existing worker-drain control
   and require a fully drained status. Account for every old worker replica.
3. Upgrade all backend/worker processes to code that understands persisted policy
   markers; then enable enrollment and resume claims.
4. Observe stopped-unknown and budget-exhausted outcomes, provider-call receipts and
   required/optional node completion before expanding usage.
5. To stop enrollment, disable the flag. Continue using policy-aware workers until
   every marked run is terminal. Do not roll back to old worker code while marked
   runs are claimable: old code ignores markers and can repeat uncertain calls.

Existing drain control uses its dedicated operator database configuration and
access grants. Do not edit leases, receipts, claim counters or run policy metadata
to force a retry. A raw database rollback or mixed-version rollout can defeat the
new retry guard even though ordinary artifact fencing still works.

The retained fixed workflow, legacy chat/tasks, images and pre-run interpretation
or owned-site extraction are outside this enrollment. Their retry exposure is
listed in responses-workflow-diagnostics.md. Extending governance to those distinct
contracts requires a separate change; this PR does not refactor the orchestrator.

## Verification and limits

Use offline MockTransport/fake services to exercise repeated HTTP 503, HTTP 408,
timeout after send, explicit zero-usage incomplete, restart after reservation,
cancellation, stale/expired leases, exhaustion, aggregate allowances and correlation.
Assert actual captured POST count, persisted receipts and terminal/retry decisions.
Assert secrets, user text, full schemas and raw provider failures are absent from
ordinary logs. Retain existing graph completion/recovery tests.

Real PostgreSQL coverage lives in `tests/test_responses_governance_postgresql.py`.
Set `MVP_TEST_DATABASE_URL` to a dedicated disposable database whose name contains
`smm_mvp_test`, then run `python -m pytest -q tests/test_responses_governance_postgresql.py`.
The shared fixture applies Alembic migrations. Test-only triggers fail writes,
defer failures to COMMIT, or terminate the owning database connection. Provider
HTTP and source acquisition are mocked; worker/service transactions and ownership
checks are real. Tests remove their triggers/functions and run data.
They verify rollback, competing replacement claims, stale-owner fencing, lease
retention until expiry on an uncommitted transition, and lease release on a
committed terminal/deferred transition. Unknown outcomes never repeat a POST;
known HTTP 503 recovery remains bounded by three sends.

Receipt persistence errors must not replace an existing provider HTTP/envelope,
transport or cancellation exception. The original exception keeps a content-free
note and ordinary logs record only IDs and error types. If no provider failure
exists, a receipt persistence error still aborts success. If persisting the retry
decision or failure transition also fails, the original provider error escapes
the worker with a safe note; no uncommitted retry or lease release is assumed.
The attempt marker cleanup is independent of the durable Job lease. Recovery
uses the committed reservation/receipt after expiry, including the conservative
case where a receipt rolled back and only a reserved outcome remains.

Provider logs and billing records are needed to reconcile real charges. Requested
output cap, reported zero counters and successful offline tests cannot establish
that an external request was not charged. Historical logs can be incomplete; the
analysis tool explicitly reports its denominator and missing-correlation limits.
