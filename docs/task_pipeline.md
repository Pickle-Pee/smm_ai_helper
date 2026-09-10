# Task pipeline architecture

This document describes the current `/tasks` architecture after the task/agent refactor.

The goal of this layer is to keep the API router thin and move task orchestration into service-layer components.

## Public API

The main task endpoints are:

- `POST /tasks/start`
- `POST /tasks/answer`
- `GET /tasks/{task_id}`
- `GET /tasks/by_user/{telegram_id}`

The public response contract is unchanged:

- `need_info` for clarification flows
- `done` for completed task flows
- optional `image` payload for image-capable modes
- saved task history in the `tasks` table

## High-level flow

```text
/tasks/start or /tasks/answer
  -> tasks router
  -> UserService / AgentRegistry validation
  -> TaskPipelineService
  -> TaskFinalizationService claim or canonical replay
  -> TaskRouter
  -> ClarificationService, if needed
  -> AgentRunner
  -> QCService, if needed
  -> TaskImageService, if mode=image or text+image
  -> TaskCompletionService fenced atomic response + Task history + claim release
```

## Router responsibilities

File: `app/routers/tasks.py`

The router should stay thin. It is responsible for:

- FastAPI endpoint definitions
- request/response schema binding
- basic HTTP errors
- getting the DB session through `Depends(get_session)`
- delegating business logic to services

The router should not contain:

- direct SQL queries for task history
- direct `Task(...)` persistence logic
- agent-specific business rules
- task-session orchestration logic
- LLM routing/QC logic

## Main services

### `TaskPipelineService`

File: `app/services/task_pipeline.py`

Coordinates the multi-step task flow.

Key methods:

- `start_task(...)`
- `answer(...)`
- `get_session(...)`
- `_handle_clarification(...)`
- `_run_agent_with_qc(...)`
- `_finalize_session(...)`

It owns the orchestration sequence but delegates specialized work to smaller services.

### `TaskSessionService`

File: `app/services/task_session_service.py`

Persists temporary multi-step task state in the database.

It stores:

- `session_id`
- `agent_type`
- `task_description`
- `mode`
- `answers`
- `questions_asked`
- `request_id`
- `user_id`

This replaced the previous in-memory session storage.

### `TaskRouter`

File: `app/services/task_router.py`

Routes a task into runtime execution metadata:

- `complexity`: `light` or `hard`
- `model`
- `max_output_tokens`
- `needs_clarification`
- `next_questions`
- `needs_qc`

The router uses the light model to make routing decisions, then normalizes the result.

If LLM routing fails, it falls back to deterministic defaults.

### `ClarificationService`

File: `app/services/clarification_service.py`

Generates short clarification questions when the router marks a task as incomplete.

Rules:

- maximum 3 questions returned at once
- maximum 6 questions per session
- if possible, continue with assumptions rather than over-asking

### `AgentRegistry`

File: `app/services/agent_registry.py`

Single source of truth for supported task agents.

Currently supported agent types:

- `strategy`
- `content`
- `analytics`
- `promo`
- `trends`

Also stores hard-agent metadata:

- `strategy`
- `analytics`

New agents should be registered here first.

### `AgentInputBuilder`

File: `app/services/agent_input_builder.py`

Builds agent-specific input from generic task data.

It prepares:

- `brief`
- agent-specific `kwargs`
- optional `qc_issues`

Example: `content` can receive `days` from either `answers.days` or `answers.period`.

### `AgentRunner`

File: `app/services/agent_runner.py`

Executes the selected agent.

It should only:

1. resolve the agent class through `AgentRegistry`
2. build input through `AgentInputBuilder`
3. apply model/token overrides
4. call `agent.run(...)`
5. normalize output through `AgentOutputBuilder`

It should not contain agent-specific input rules or output formatting details.

### `AgentOutputBuilder`

File: `app/services/agent_output_builder.py`

Normalizes raw agent output into the task result contract:

```json
{
  "content": "...",
  "format": "markdown",
  "assumptions": [],
  "confidence": "medium",
  "warnings": []
}
```

It delegates markdown formatting to presenters.

### `QCService`

File: `app/services/qc_service.py`

Checks generated task output and returns concrete revision issues.

If issues are returned, `TaskPipelineService` runs the agent again with `qc_issues` added to the agent input.

### `TaskImageService`

File: `app/services/task_image_service.py`

Builds optional image output for task sessions.

It only runs for:

- `mode=image`
- `mode=text+image`

It maps task answers into the image generation service.

### `TaskResultService`

File: `app/services/task_result_service.py`

Persists results from the legacy direct-agent path to `tasks`. Standalone session completion now uses `TaskCompletionService` for atomic canonical response/history; it does not call this service.

It supports:

- direct completed task persistence
- completed task persistence from `TaskSessionState`
- merging `session_state.answers` with final `extra_answers`
- resolving `user_id` from stored `session_state.user_id`

### `TaskHistoryService`

File: `app/services/task_history_service.py`

Reads task history:

- one task by id
- recent tasks by Telegram user id

The router should use this service instead of building SQL queries directly.

## Compatibility alias

File: `app/services/orchestrator.py`

`OrchestratorService` is kept as a backward-compatible alias:

```python
from app.services.task_pipeline import TaskPipelineService

OrchestratorService = TaskPipelineService
```

New code should import `TaskPipelineService` directly.

## Persistence model

There are two kinds of task persistence:

### Durable session state and canonical replay

Stored by `TaskSessionService` in task-session records.

Used during clarification and retained after `done`. `completed_response` freezes the successful response; later answers return it without changing answers or executing external services. No session deletion occurs on completion.

### Final task history

Stored by `TaskCompletionService` in the `tasks` table, atomically with the session response and claim release.

Used for user history and task retrieval.

### Standalone execution ownership and failure contract

`TaskFinalizationService` uses the task session's primary-key row plus two nullable columns: a random `finalization_token` and PostgreSQL `TIMESTAMPTZ finalization_lease_until`. Constraints require both claim fields to be null or both present, and prohibit a claim on a completed session. No generic Job/queue/Registry binding is added.

Every continuation, including `/tasks/start`, first claims the session in a short row-locked transaction. Routing is inside the claim because TaskRouter itself may call a model before deciding whether more clarification is needed. PostgreSQL `clock_timestamp()` sampled after locking determines ownership expiry. The winning caller alone records its answer and receives a detached snapshot. Another backend process sees the same claim; stale ORM identity-map state is refreshed from the locked row. Concurrent final answers with conflicting values use the winning snapshot and converge on its canonical completion.

The claim commits before external work. Each external stage checks the token/lease in another short transaction and closes it before calling routing, clarification, AgentRunner, QC or image generation. A normal final attempt runs AgentRunner once, QC at most once and image generation at most once; QC may deliberately request one agent revision. An AgentRunner may itself make multiple provider calls for an agent's established contract. These are not concurrency duplicates.

Other callers poll PostgreSQL every 100 ms with the transaction closed between checks. They return the persisted canonical response once it exists. No asyncio lock or Redis is authoritative. `TaskCompletionService` locks and checks ownership, then saves exactly one Task row, the response and claim release in the same transaction. A failed commit rolls back all three. Clarification saves the question count and releases its claim, preserving the existing `need_info` response rather than marking the session completed.

`TASK_FINALIZATION_TIMEOUT_SECONDS` defaults to 240 (configurable 5–900). The lease is timeout + 30 seconds; there is no heartbeat or lease renewal. A caller waits at most lease + 5 seconds for ownership before returning HTTP 503 with `Retry-After: 5`. Once it owns the session it makes at most one execution attempt, bounded by the execution timeout, with up to five seconds for cleanup. Under normal DB availability, maximum wait plus execution/cleanup is therefore approximately 520 seconds at defaults. Configure client/proxy deadlines accordingly; a client timeout is not proof that execution did not complete.

On provider failure, timeout or request cancellation, the service rolls back and releases only its own token. Timeout/lost ownership/busy wait exhaustion return retryable HTTP 503; existing unexpected provider/persistence errors still fail the request. If cleanup cannot reach PostgreSQL, or the process dies, the durable claim expires and a later request can reclaim it. A waiting contender can also acquire after failure/expiry; there is no background standalone recovery and no automatic unbounded provider retry loop. Each caller can execute only one claimed attempt. Stale owners cannot enter another external stage, publish a response or clear a successor's claim.

This gives one local final execution for ordinary competing requests within a valid claim and one canonical persisted completion/history. It is not an exactly-once external-provider guarantee across crashes, timeouts, lost commit acknowledgements, process suspension or partitions. An already accepted remote call may outlive cancellation, and recovery may call it again or leave an unused generated image. Later replay of a successfully committed response does not repeat any external stage. Standalone Telegram client waiting remains synchronous; independent durable Telegram delivery belongs to the fixed marketing workflow only.

Public DTO fields for `/tasks/start`, `/tasks/answer` and history are unchanged. Existing bearer/actor and owner checks remain required. Standalone sessions never enter MarketingWorkflowService or Module Registry execution.

Migration `20260909_0008` follows `20260909_0007`, adding only the claim columns and constraints. Upgrade initializes existing sessions as unclaimed, retaining answers/completed responses/history. Stop/drain backend requests during rollout: older processes do not honor the new claims. Downgrade requires stopped backends, drops active ownership metadata and preserves the retained session/history data. Restart/retry unfinished sessions using the matching application version; the old version has no pre-execution concurrency protection.

## Testing strategy

Current unit-test coverage focuses on deterministic service logic without external systems.

Covered:

- `AgentRegistry`
- `AgentInputBuilder`
- `AgentOutputBuilder`
- `TaskRouter`
- `TaskResultService`
- `TaskPipelineService` flow steps

Unit tests avoid:

- real OpenAI calls
- real database connections
- real image generation
- Telegram bot polling

Run checks:

```bash
pytest
python -m compileall app bot
git diff --check
```

## When adding a new agent

Recommended steps:

1. Add the agent class under `app/agents`.
2. Register it in `AgentRegistry`.
3. Add hard/light metadata if needed.
4. Add input rules in `AgentInputBuilder`, if the agent needs custom kwargs.
5. Add presenter formatting if the raw output needs a custom markdown layout.
6. Add tests for registry/input/output behavior.
7. Verify `/tasks/start` works with the new `agent_type`.

## What should not be reintroduced

Avoid bringing back:

- in-memory task sessions
- duplicated supported-agent lists
- SQL query logic inside `tasks.py`
- direct `Task(...)` construction inside router endpoints
- agent-specific kwargs inside `AgentRunner`
- presenter formatting inside `AgentRunner`
- LLM routing logic inside router endpoints

## Next recommended architecture steps

ChatService, persistent BrandProfile, the thin legacy agent wrapper and the fixed opt-in workflow mentor already exist. Broader usage/billing controls and generalized learning remain future work.

PostgreSQL regressions in `tests/test_task_finalization_postgresql.py` invoke real concurrent `answer()` calls with synchronized provider doubles and separate sessions. They prove one router/agent/QC/image path, canonical replay/history, no provider-spanning transaction/row lock, failure/cancellation/timeout/commit recovery, process-death recovery, stale-owner fencing and clarification release. `tests/test_task_replay_http.py` checks unchanged response shapes and retryable HTTP errors. Migration tests cover upgrade/downgrade/re-upgrade and schema/model alignment. Set the explicitly disposable `MVP_TEST_DATABASE_URL` described in README; PostgreSQL tests skip when it is absent.
