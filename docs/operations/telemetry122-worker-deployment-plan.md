# Telemetry #122: revised worker deployment contract

The consolidated [first-production-rollout runbook](first-production-rollout.md)
now supplies the #122/#123 source manifest, reconnaissance collector, bootstrap
design, ordered cutover and rollback plan. Production remains NO-GO pending
independent topology/evidence review and separate authorization.

Status: prepared for review, **no production access or rollout authorized**. The
first production installation remains **NO-GO** until the legacy bootstrap gate in
[Worker Drain Control](worker-drain-control.md#first-rollout-legacy-bootstrap) is
satisfied. A new pause row cannot stop a worker built before this control.

This contract updates the F3 admission/drain portions of the local #122 preparation
plan from commit `39d369d` (merge `f964237`, parent `55b0987`). That package's image
attestation, source/configuration fingerprints, permissions, ownership, retained
image/volume checks, telemetry verification and authorization requirements remain
separate gates. It is not tracked in the #122 merge and is not transplanted as an
installer here. Its `barrier.json`, unconditional NO_GO_ADMISSION_CONTROL gate and
`unfinished_jobs == 0` predicate must **not** be reused as the drain gate for a
control-aware release. The old five-file overlay also cannot install this feature:
the new model/control/CLI/claim code and migration require a coherent reviewed
release image. Rebuild/version its manifest and structural checks in a separately
authorized release preparation before use.

## Replacement for F3 in subsequent releases

Use live PostgreSQL evidence produced by the reviewed operator CLI. The deployment
orchestration must invoke the CLI itself against the authoritative worker database,
capture its exit status and safe JSON, and bind the result to the pause epoch it
owns. Reading an old JSON file, accepting an operator `verified=true`, or checking
only a process-local flag is not sufficient. Never print the operator DSN.

The cutover predicate is:

```text
same authoritative database for all inventoried compatible workers
AND every worker/executor uses the guarded fixed/graph claim implementation
AND live schema_version == worker_drain.v1
AND live epoch == captured pause epoch E
AND live admission == paused
AND live drained == true
AND fixed.outstanding_attempts == graph.outstanding_attempts == 0
AND fixed.active_leases == graph.active_leases == 0
AND no competing operator may resume during the replacement window
AND existing structural/source/configuration/compatibility gates pass
```

Pending and deferred jobs may remain. A `running` Job with a cleared current token
and future retry time represents waiting durable work; outstanding attempt
markers separately account for any superseded call still running. Queued or
running graph runs may wait for their next claim. Do not require those populations
to be empty, alter their times/statuses or consume retries to make a deployment
gate green. `outstanding_attempts` counts the distinct union of current
JobExecution tokens and durable `worker_attempts(job_id, claim_token)` markers.
Count expired and superseded attempts: a replacement can finish while the older
provider call is still running, and only the older attempt's unwound cleanup can
release its marker. Expiry or supersession alone cannot prove a call stopped.

`python -m app.worker_control status --require-drained --expect-epoch E` is the
machine-verifiable
gate. It reads PostgreSQL on each invocation; its nonzero exit blocks replacement.
Saved output is an audit record, not authorization. The schema contains only
aggregate metadata and server observation time; it contains no jobs, prompts,
credentials or claim tokens.

## Authorized future procedure

The following is a contract for a future explicitly authorized operation. It does
not execute migration, deployment, production reads, or provider calls now.

1. Establish worker inventory, actual image/code provenance and target compatibility.
   Include every fixed and graph instance and any direct executor. If any worker
   ignores the control, use the legacy bootstrap gate instead. Verify the new
   migration is present without modifying merged migrations.
2. Configure the protected operator PostgreSQL connection and read live status.
   Capture current epoch N. Issue
   `python -m app.worker_control pause --expect-epoch N`, require a successful
   committed response, and retain returned epoch E. If the response is uncertain,
   reread status and reconcile; do not proceed on an assumed commit.
3. Keep API/Telegram durable job producers running. Poll live
   `python -m app.worker_control status --require-drained --expect-epoch E`.
   Bound the operational waiting
   window, retaining paused state when the window expires; changing admission,
   timeout, retry ownership or job metadata to force a pass is prohibited.
4. Immediately before stopping a worker, rerun that live gate against the same DB.
   Keep operator exclusivity and the same paused epoch through the whole operation.
   Once drained, SIGTERM is safe for idle lane tasks. Keep PostgreSQL, media and
   durable job/artifact/delivery state intact. Do not start an unguarded worker or
   assume a larger Docker stop timeout drains active OpenAI requests.
5. Replace only the authorized services using the approved immutable release.
   Check actual image source, runtime/configuration identity and both fixed/graph
   startup. A replacement worker must remain paused even after restart; startup
   alone is not a drain proof. Repeat the live drained gate at E.
6. After structural acceptance, issue
   `python -m app.worker_control resume --expect-epoch E`. Confirm open
   admission and its returned epoch. Due scans recover retained pending/deferred
   jobs even if Redis hints were lost. Preserve #122 telemetry/model/budget/flags
   and existing durable retry ownership; no diagnostic provider POST is needed.

If the candidate fails startup while paused, keep admission paused. Restore an
already attested **control-aware** compatible image under the same live gate,
verify both lanes, then resume explicitly. An old pre-control rollback image is
not eligible for this procedure: it requires the external bootstrap maintenance
barrier and full legacy backlog drain. Do not delete tokens/markers/leases/jobs, rewind
migrations, clear Redis, or start a second unguarded worker as incident recovery.

DB failure, missing control row/schema, epoch drift, outstanding expired or
superseded attempts, crash-retained or cleanup-failed attempt markers,
unknown process identity, incomplete migration or bypass executors returns STOP
or WAIT; it never opens admission or supplies synthetic evidence. A stale status
file remains invalid even when its `drained` field is true.

A retained marker can conservatively block an update after a crash or DB cleanup
failure even when no provider call remains. Keep NO-GO and use a separately
authorized recovery procedure with independent proof that the owning attempt
cannot still perform provider work. Neither the live CLI nor a deployment gate
force-clears markers or current claim tokens. Cancellation cleanup after SIGTERM
may remove an unwound attempt's marker, but its recoverable current token continues
to block drain; this does not make active-worker SIGTERM a valid drain procedure.

## Bootstrap evidence remains independent

For the first installation, the updated contract requires external evidence of
closed producer ingress and completion of already accepted producers, a full
legacy backlog drain and confirmed absence of legacy processes. The runbook lists
the exact route boundary and the minimal proxy/network/request-draining mechanism.
That mechanism is not available or proven merely because this PR exists. No
manual `barrier.json` is accepted as a replacement. Keep NO-GO until its topology,
monitoring and Telegram retry behavior are reviewed and demonstrated under a
separate authorized maintenance plan.

Local tests prove the reusable admission contract with provider fakes and real
disposable PostgreSQL. They do not prove the production bootstrap, actual image
permissions or provider health, and do not authorize merging or rollout.
