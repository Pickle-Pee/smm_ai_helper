import asyncio
from types import SimpleNamespace

from app.services.task_result_service import TaskResultService
from app.services.task_session_service import TaskSessionState


class FakeDbSession:
    def __init__(self):
        self.added = []
        self.committed = False
        self.refreshed = []

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.committed = True

    async def refresh(self, item):
        self.refreshed.append(item)


def test_save_done_task_persists_task_with_expected_fields():
    db_session = FakeDbSession()

    task = asyncio.run(
        TaskResultService.save_done_task(
            db_session=db_session,
            user_id=42,
            agent_type="content",
            task_description="Сделай пост",
            answers={"topic": "AI"},
            result={"content": "Готово"},
        )
    )

    assert db_session.added == [task]
    assert db_session.committed is True
    assert db_session.refreshed == [task]
    assert task.user_id == 42
    assert task.agent_type == "content"
    assert task.task_description == "Сделай пост"
    assert task.answers == {"topic": "AI"}
    assert task.result == {"content": "Готово"}
    assert task.status == "done"


def test_save_error_task_persists_error_with_expected_fields():
    db_session = FakeDbSession()

    task = asyncio.run(
        TaskResultService.save_error_task(
            db_session=db_session,
            user_id=42,
            agent_type="content",
            task_description="Сделай пост",
            answers={"topic": "AI"},
            error="Agent failed",
        )
    )

    assert db_session.added == [task]
    assert db_session.committed is True
    assert db_session.refreshed == [task]
    assert task.user_id == 42
    assert task.agent_type == "content"
    assert task.task_description == "Сделай пост"
    assert task.answers == {"topic": "AI"}
    assert task.result is None
    assert task.status == "error"
    assert task.error == "Agent failed"


def test_save_done_task_from_anonymous_session_adds_extra_answers():
    db_session = FakeDbSession()
    session_state = TaskSessionState(
        session_id="session-1",
        agent_type="strategy",
        task_description="Сделай стратегию",
        mode="text",
        answers={"audience": "эксперты"},
        user_id="anonymous",
    )

    task = asyncio.run(
        TaskResultService.save_done_task_from_session(
            db_session=db_session,
            session_state=session_state,
            result={"content": "Стратегия"},
            extra_answers={"platform": "Telegram"},
        )
    )

    assert task.user_id is None
    assert task.agent_type == "strategy"
    assert task.task_description == "Сделай стратегию"
    assert task.answers == {
        "audience": "эксперты",
        "platform": "Telegram",
    }
    assert task.result == {"content": "Стратегия"}
    assert task.status == "done"


def test_save_done_task_from_known_user_session_resolves_user(monkeypatch):
    db_session = FakeDbSession()
    session_state = TaskSessionState(
        session_id="session-2",
        agent_type="analytics",
        task_description="Проанализируй канал",
        mode="text",
        answers={"channel": "Telegram"},
        user_id="12345",
    )

    async def fake_get_by_telegram_id(_db_session, telegram_id):
        assert _db_session is db_session
        assert telegram_id == 12345
        return SimpleNamespace(id=777)

    monkeypatch.setattr(
        "app.services.task_result_service.UserService.get_by_telegram_id",
        fake_get_by_telegram_id,
    )

    task = asyncio.run(
        TaskResultService.save_done_task_from_session(
            db_session=db_session,
            session_state=session_state,
            result={"content": "Аналитика"},
        )
    )

    assert task.user_id == 777
    assert task.agent_type == "analytics"
    assert task.answers == {"channel": "Telegram"}
    assert task.result == {"content": "Аналитика"}
