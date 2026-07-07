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
  -> TaskRouter
  -> ClarificationService, if needed
  -> AgentRunner
  -> QCService, if needed
  -> TaskImageService, if mode=image or text+image
  -> TaskSessionService cleanup
  -> TaskResultService persistence
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

Persists completed task results to the `tasks` table.

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

### Temporary session state

Stored by `TaskSessionService` in task-session records.

Used while a task is still in progress and may need clarification.

Deleted after the task reaches `done`.

### Final task history

Stored by `TaskResultService` in the `tasks` table.

Used for user history and task retrieval.

## Testing strategy

Current unit-test coverage focuses on deterministic service logic without external systems.

Covered:

- `AgentRegistry`
- `AgentInputBuilder`
- `AgentOutputBuilder`
- `TaskRouter`
- `TaskResultService`
- `TaskPipelineService` flow steps

The tests avoid:

- real OpenAI calls
- real database connections
- real image generation
- Telegram bot polling

Run checks:

```bash
pytest
python -m compileall app
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

The task/agent core is now in a stable shape.

Recommended next steps:

1. Add integration tests for `/tasks/start` and `/tasks/answer`.
2. Refactor legacy `/agents/{agent_type}/run` into a thin compatibility wrapper or remove it later.
3. Move large chat flow from `chat_router.py` into `ChatService`.
4. Add `BrandProfileService` and persistent brand profiles.
5. Add usage tracking before introducing plans/billing.
6. Add learning/mentor layer after stable task execution.
