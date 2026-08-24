# Durable Job persistence product contract

Status: reconciled pre-implementation design; no runtime Job model, service, migration, queue, or worker exists yet.

## Responsibility

A durable Job represents one future asynchronous execution request whose canonical lifecycle record belongs in PostgreSQL. It is intentionally narrower than a workflow:

- `MarketingRun` owns multi-step workflow progress and state.
- `MarketingArtifact` owns named durable workflow outputs.
- `Job` owns one request's immutable input, execution status, result/error, and lifecycle timestamps.

A Job result does not replace a MarketingArtifact, and Job status does not replace MarketingRun status.

## Ownership

Ownership is optional and exclusive:

- a MarketingRun-owned Job may name one workflow step and is deleted with its run;
- a runless user-owned Job survives user deletion with its user reference cleared;
- a system/anonymous Job has neither reference;
- a Job cannot reference both a MarketingRun and a direct user, and a runless Job cannot name a workflow step.

A Job has no direct Module Registry ownership or execution binding. Its validated `kind` is persistence metadata whose supported values must be defined by later producers/workers.

## Closed lifecycle

```text
pending -> running -> succeeded
                   \-> failed
```

- `pending`: durable but not started; no result, error, start, or completion time.
- `running`: started; no result, error, or completion time.
- `succeeded`: terminal; requires start/completion times and a structured result; prohibits error.
- `failed`: terminal; requires start/completion times and a bounded non-empty error; prohibits result.

Same-state transitions, skipped states, and terminal transitions are illegal. Retry, cancellation, timeout, dead-letter, delivery, and worker-lease states are not part of this vocabulary.

## Persistence and transaction boundary

The planned internal service creates, loads, lists run Jobs deterministically, and performs row-locked legal transitions. It may add/flush but never commits or rolls back. The caller owns the transaction, including atomic combinations of Job, MarketingRun, and MarketingArtifact changes.

PostgreSQL commit is the durability boundary. A committed Job is not proof that work was published, claimed, or executed. Cross-system publication/recovery and semantic deduplication need later approved queue and reliability changes; this foundation does not introduce an outbox.

## Compatibility and non-goals

The foundation must not change existing API/Telegram contracts, standalone task execution, MarketingRun/MarketingArtifact behavior, Marketing Orchestrator planning, Quality Gates, Module Registry metadata, agents/presenters, or LLM/QC call counts.

It introduces no Redis, queue framework, worker, scheduler, polling, delivery, module execution, retry/backoff, idempotency, ordering, concurrency limit, cancellation, timeout, API endpoint, Telegram UX, or OpenAI/QC call.

The exact schema, constraints, indexes, service signatures, migration parent, failure semantics, and test obligations are normative in `openspec/changes/add-durable-job-persistence/`.
