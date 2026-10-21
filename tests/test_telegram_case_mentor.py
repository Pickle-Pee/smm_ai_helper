"""Offline mentor transport: case binding, restart, failures and explicit entry."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import backend
from bot.copilot_flow import run_callback, reset
from bot.handlers import mentor
from tests.test_telegram_copilot import message, context, text_sent, RID


def explanation():
    return {"schema_version": "case_mentor.v1", "run_id": RID, "sections": [
        {"title": f"Раздел {i}", "paragraphs": ["Сохранённое основание <b>буквально</b>"]} for i in range(8)]}


def test_restart_callback_uses_clicking_actor_and_binds_questions(monkeypatch):
    request = AsyncMock(side_effect=[explanation(), {"run_id": RID, "paragraphs": ["Проверить сохранённую гипотезу"]}])
    monkeypatch.setattr(backend, "request", request)
    async def check():
        msg, state = message(actor=42), context(42)
        callback = SimpleNamespace(message=msg, from_user=SimpleNamespace(id=321),
            data=run_callback(RID).replace("cs:", "cm:"), answer=AsyncMock())
        await mentor.explain(callback, state)
        assert request.call_args_list[0].args == ("POST", f"/copilot/runs/{RID}/mentor", 321)
        assert await state.get_state() == mentor.MentorStates.question.state
        assert text_sent(msg).count("Сохранённое основание") == 8
        followup = message("Что проверить первым?", mid=2, actor=321)
        await mentor.question(followup, state)
        assert request.call_args.args == ("POST", f"/copilot/runs/{RID}/mentor/questions", 321)
        assert request.call_args.kwargs["payload"]["request_key"] == "tg:321:321:2"
        assert "сохранённую гипотезу" in text_sent(followup)
        await reset(followup, state)
        feedback = message("/case_feedback worked | есть продажи", actor=321)
        await mentor.feedback(feedback, state)
        assert request.await_count == 2
    asyncio.run(check())


def test_malformed_group_and_failure_leave_original_case_available(monkeypatch):
    request = AsyncMock(side_effect=backend.BackendError("hidden"))
    monkeypatch.setattr(backend, "request", request)
    async def check():
        msg, state = message(), context()
        callback = SimpleNamespace(message=msg, from_user=msg.from_user, data="cm:bad", answer=AsyncMock())
        await mentor.explain(callback, state)
        request.assert_not_awaited()
        callback.data = run_callback(RID).replace("cs:", "cm:")
        msg.chat.type = "group"
        await mentor.explain(callback, state)
        request.assert_not_awaited()
        msg.chat.type = "private"
        await mentor.explain(callback, state)
        assert "/copilot_runs" in text_sent(msg) and "hidden" not in text_sent(msg)
        assert await state.get_state() is None
    asyncio.run(check())


def test_feedback_preserves_reported_metrics(monkeypatch):
    request = AsyncMock(return_value={})
    monkeypatch.setattr(backend, "request", request)
    async def check():
        msg, state = message("/case_feedback сработало | получили заявки | CPL 400"), context()
        await state.update_data(mentor_run_id=RID)
        await state.set_state(mentor.MentorStates.question)
        await mentor.feedback(msg, state)
        payload = request.call_args.kwargs["payload"]
        assert payload["outcome"] == "worked" and payload["metrics"] == "CPL 400"
        assert "не независимая проверка" in text_sent(msg)
    asyncio.run(check())
