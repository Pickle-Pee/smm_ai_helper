import asyncio
from unittest.mock import AsyncMock

import pytest

import app.services.task_pipeline as task_pipeline_module
from app.services.task_pipeline import TaskPipelineService
from app.services.task_session_service import TaskSessionState


@pytest.fixture(autouse=True)
def fake_claim_check(monkeypatch):
    # Claim/transaction behavior is exercised against PostgreSQL in the integration suite.
    monkeypatch.setattr(task_pipeline_module.TaskFinalizationService, "check_owned", AsyncMock())


class FakeDbSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


class FakeAgentRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def run(self, **kwargs):
        self.calls.append(kwargs)
        return self.results.pop(0)


class FakeQCService:
    def __init__(self, issues):
        self.issues = issues
        self.calls = []

    async def find_issues(self, task_description, content):
        self.calls.append(
            {
                "task_description": task_description,
                "content": content,
            }
        )
        return self.issues


class FakeImageService:
    def __init__(self, image_payload=None):
        self.image_payload = image_payload
        self.calls = []

    async def generate_for_task_session(self, session_state):
        self.calls.append(session_state)
        return self.image_payload


def make_session_state(**overrides):
    data = {
        "session_id": "session-1",
        "agent_type": "strategy",
        "task_description": "Сделай стратегию",
        "mode": "text",
        "answers": {"audience": "эксперты"},
        "questions_asked": 0,
        "request_id": "request-1",
        "user_id": "user-1",
    }
    data.update(overrides)
    return TaskSessionState(**data)


def test_handle_clarification_returns_need_info_and_persists_state(monkeypatch):
    saved_states = []

    async def fake_save(_db_session, state):
        saved_states.append(state)
        await _db_session.commit()
        return state

    monkeypatch.setattr(task_pipeline_module.TaskFinalizationService, "finish_clarification", fake_save)

    db_session = FakeDbSession()
    session_state = make_session_state()
    questions = [
        {"key": "audience", "question": "Кто аудитория?"},
        {"key": "goal", "question": "Какая цель?"},
        {"key": "platform", "question": "Какая площадка?"},
    ]
    decision = {
        "needs_clarification": True,
        "next_questions": questions,
    }

    response = asyncio.run(
        TaskPipelineService()._handle_clarification(
            db_session=db_session,
            session_state=session_state,
            decision=decision,
        )
    )

    assert response == {
        "status": "need_info",
        "session_id": "session-1",
        "questions": questions,
    }
    assert session_state.questions_asked == 3
    assert saved_states == [session_state]
    assert db_session.commits == 1


def test_handle_clarification_returns_none_when_not_needed():
    response = asyncio.run(
        TaskPipelineService()._handle_clarification(
            db_session=FakeDbSession(),
            session_state=make_session_state(),
            decision={"needs_clarification": False},
        )
    )

    assert response is None


def test_run_agent_with_qc_returns_original_result_when_qc_not_needed():
    service = TaskPipelineService()
    service.agent_runner = FakeAgentRunner(
        results=[{"content": "Готово", "confidence": "high", "warnings": []}],
    )
    service.qc_service = FakeQCService(issues=[])

    result = asyncio.run(
        service._run_agent_with_qc(
            db_session=FakeDbSession(),
            session_state=make_session_state(),
            decision={
                "model": "model-hard",
                "max_output_tokens": 1200,
                "needs_qc": False,
            },
        )
    )

    assert result == {"content": "Готово", "confidence": "high", "warnings": []}
    assert len(service.agent_runner.calls) == 1
    assert service.qc_service.calls == []


def test_run_agent_with_qc_revises_result_and_appends_warnings():
    service = TaskPipelineService()
    service.agent_runner = FakeAgentRunner(
        results=[
            {"content": "Слишком общо", "confidence": "medium", "warnings": []},
            {"content": "Исправлено", "confidence": "high", "warnings": ["old warning"]},
        ],
    )
    service.qc_service = FakeQCService(issues=["Добавить конкретные шаги"])

    result = asyncio.run(
        service._run_agent_with_qc(
            db_session=FakeDbSession(),
            session_state=make_session_state(),
            decision={
                "model": "model-hard",
                "max_output_tokens": 1600,
                "needs_qc": True,
            },
        )
    )

    assert result == {
        "content": "Исправлено",
        "confidence": "high",
        "warnings": ["old warning", "Добавить конкретные шаги"],
    }
    assert len(service.agent_runner.calls) == 2
    assert service.agent_runner.calls[1]["qc_issues"] == ["Добавить конкретные шаги"]
    assert service.qc_service.calls == [
        {
            "task_description": "Сделай стратегию",
            "content": "Слишком общо",
        }
    ]


def test_finalize_session_delegates_atomic_completion_and_returns_done_response(monkeypatch):
    completions = []

    async def fake_complete(db, state, response):
        completions.append((db, state, response))
        return response

    monkeypatch.setattr(task_pipeline_module.TaskCompletionService, "complete", fake_complete)

    service = TaskPipelineService()
    image_payload = {"url": "/images/test.png"}
    service.task_image_service = FakeImageService(image_payload=image_payload)

    db_session = FakeDbSession()
    session_state = make_session_state(mode="text+image")
    result = {"content": "Готово"}

    response = asyncio.run(
        service._finalize_session(
            db_session=db_session,
            session_state=session_state,
            result=result,
            usage={"total_tokens": 100},
        )
    )

    assert response == {
        "status": "done",
        "session_id": "session-1",
        "result": result,
        "image": image_payload,
    }
    assert completions == [(db_session, session_state, response)]
    assert db_session.commits == 0
    assert service.task_image_service.calls == [session_state]


def test_answer_raises_for_unknown_session(monkeypatch):
    async def fake_acquire(*_args):
        raise ValueError("Unknown session")

    monkeypatch.setattr(task_pipeline_module.TaskFinalizationService, "acquire", fake_acquire)

    with pytest.raises(ValueError, match="Unknown session"):
        asyncio.run(
            TaskPipelineService().answer(
                db_session=FakeDbSession(),
                session_id="missing",
                key="audience",
                value="эксперты",
            )
        )


def test_busy_claim_wait_is_bounded_and_does_not_execute(monkeypatch):
    acquire = AsyncMock(return_value=None)
    clock = iter([0, 276])  # Default wait limit is 240 + 30 + 5 seconds.
    monkeypatch.setattr(task_pipeline_module.settings, "TASK_FINALIZATION_TIMEOUT_SECONDS", 240)
    monkeypatch.setattr(task_pipeline_module.TaskFinalizationService, "acquire", acquire)
    monkeypatch.setattr(task_pipeline_module, "monotonic", lambda: next(clock))
    pipeline = TaskPipelineService()
    pipeline._continue_session = AsyncMock()
    with pytest.raises(task_pipeline_module.TaskFinalizationUnavailable, match="still executing"):
        asyncio.run(pipeline.answer(FakeDbSession(), "busy", "goal", "sales"))
    acquire.assert_awaited_once()
    pipeline._continue_session.assert_not_called()
