"""Standalone transport compatibility and retryable errors; no external calls."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.main import task_finalization_unavailable
from app.routers import tasks as tasks_module
from app.services.task_finalization_service import TaskFinalizationUnavailable
from tests.test_http_security import secured_app, request
from bot.backend import actor_headers


@pytest.mark.parametrize("status", ["need_info", "done", "busy"])
def test_answer_preserves_dto_and_retryable_failure_mapping(secured_app, monkeypatch, status):
    app, db = secured_app
    app.add_exception_handler(TaskFinalizationUnavailable, task_finalization_unavailable)
    db.scalar.return_value = "100"
    monkeypatch.setattr(tasks_module.task_pipeline, "get_session", AsyncMock(return_value=SimpleNamespace(user_id="100")))
    response = ({"status": "need_info", "session_id": "test", "questions": [{"key": "goal", "question": "Goal?"}]}
                if status == "need_info" else
                {"status": "done", "session_id": "test", "result": {"content": "saved", "format": "markdown", "assumptions": [], "confidence": "high", "warnings": []}, "image": None})
    call = AsyncMock(return_value=response, side_effect=TaskFinalizationUnavailable("retry this session") if status == "busy" else None)
    monkeypatch.setattr(tasks_module.task_pipeline, "answer", call)
    result = request(app, "POST", "/tasks/answer", headers=actor_headers(100), json={"session_id": "test", "key": "goal", "value": "sales"})
    if status == "busy":
        assert result.status_code == 503 and result.headers["Retry-After"] == "5"
        assert result.json() == {"detail": "retry this session"}
    else:
        assert result.status_code == 200 and result.json() == response
    call.assert_awaited_once()
