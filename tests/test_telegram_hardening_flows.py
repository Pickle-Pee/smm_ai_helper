"""One-shot interface actions and saved task failures, without external services."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram import Bot, types

from bot import copilot_contracts as dto, copilot_flow as flow
from bot.handlers import agent_flow, chat, history
from tests.test_telegram_copilot import context, message, patch_http, started
from tests.test_telegram_navigation_fixtures import no_selected_project

pytestmark = pytest.mark.usefixtures("no_selected_project")


def callback(data, actor=123, **kwargs):
    user = SimpleNamespace(id=actor, username=None, first_name="User", last_name=None)
    msg = message(actor=actor)
    return SimpleNamespace(data=data, id="callback", from_user=user, message=msg, answer=AsyncMock(), **kwargs)


def test_action_is_consumed_before_concurrent_backend_calls(monkeypatch):
    monkeypatch.setattr(chat, "ACTION_STORE", {})
    backend = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", backend)
    data = chat._actions_keyboard(123, [{"text": "Continue"}]).inline_keyboard[0][0].callback_data
    async def check():
        await asyncio.gather(*(chat.on_action(callback(data)) for _ in range(10)))
        assert backend.await_count == 1
        await chat.on_action(callback(data))
        assert backend.await_count == 1
    asyncio.run(check())


def test_identical_action_in_new_response_cannot_reactivate_old_keyboard(monkeypatch):
    monkeypatch.setattr(chat, "ACTION_STORE", {})
    backend = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", backend)
    old = chat._actions_keyboard(123, [{"text": "Continue"}]).inline_keyboard[0][0].callback_data
    new = chat._actions_keyboard(123, [{"text": "Continue"}]).inline_keyboard[0][0].callback_data
    assert old != new
    async def check():
        await chat.on_action(callback(old))
        backend.assert_not_called()
        await chat.on_action(callback(new))
        backend.assert_awaited_once()
        chat.ACTION_STORE.clear()  # Process restart.
        await chat.on_action(callback(new))
        assert backend.await_count == 1
    asyncio.run(check())


def test_foreign_and_group_actions_are_rejected(monkeypatch):
    monkeypatch.setattr(chat, "ACTION_STORE", {})
    backend = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", backend)
    data = chat._actions_keyboard(123, [{"text": "Continue"}]).inline_keyboard[0][0].callback_data
    async def check():
        await chat.on_action(callback(data, actor=456))
        group = callback(data)
        group.message.chat.type = "group"
        await chat.on_action(group)
        backend.assert_not_called()
    asyncio.run(check())


@pytest.mark.parametrize("handler,payload", [(history.on_task_show, "task_show:bad"),
    (history.on_task_show, "task_show:1:extra"), (history.on_task_repeat, "task_repeat:1:strategy"),
    (agent_flow.on_strategy_full, "strategy_full:bad"), (agent_flow.on_content_more, "content_more:-1"),
    (agent_flow.on_analytics_more, "analytics_more:"), (agent_flow.on_promo_more, "promo_more:1:extra"),
    (agent_flow.on_trends_more, "trends_more:" + "9" * 100)])
def test_malformed_task_callbacks_do_not_call_backend(monkeypatch, handler, payload):
    fetch = AsyncMock()
    monkeypatch.setattr(history, "fetch_task", fetch)
    asyncio.run(handler(callback(payload)))
    fetch.assert_not_called()


def test_repeat_button_is_single_use_owner_bound_and_expires_on_restart(monkeypatch):
    monkeypatch.setattr(history, "REPEAT_BUTTONS", __import__("collections").OrderedDict())
    fetch = AsyncMock(return_value={"id": 1, "agent_type": "strategy", "status": "done", "task_description": "Saved", "result": {}, "answers": {}})
    monkeypatch.setattr(history, "fetch_task", fetch)
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"task_id": 2, "result": {}, "status": "done"})
    patch_http(monkeypatch, respond)
    monkeypatch.setattr(history, "show_task", AsyncMock())
    data = history.history_item_kb(1, "strategy", 123).inline_keyboard[0][1].callback_data
    async def check():
        await history.on_task_repeat(callback(data, actor=456))
        fetch.assert_not_called()
        await asyncio.gather(*(history.on_task_repeat(callback(data)) for _ in range(10)))
        assert len(calls) == 1
        assert calls[0].url.path == "/agents/strategy/run"
        assert calls[0].headers["x-telegram-user-id"] == "123"
        history.REPEAT_BUTTONS.clear()
        await history.on_task_repeat(callback(data))
        assert len(calls) == 1
    asyncio.run(check())


def test_repeat_modified_agent_is_rejected(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(history, "fetch_task", fetch)
    data = history.history_item_kb(1, "strategy", 123).inline_keyboard[0][1].callback_data
    asyncio.run(history.on_task_repeat(callback(data.replace(":strategy:", ":content:"))))
    fetch.assert_not_called()


def test_failed_saved_task_cannot_be_presented_as_success():
    msg = message()
    asyncio.run(history.show_task(msg, {"agent_type": "strategy", "status": "error", "result": {"summary_text": "Misleading success"}}))
    assert "не завершена успешно" in msg.answer.call_args.args[0]
    assert "Misleading success" not in msg.answer.call_args.args[0]


def test_saved_long_strategy_is_not_truncated():
    msg = message()
    text = "Данные 🚀" * 2000
    asyncio.run(history.show_task(msg, {"agent_type": "strategy", "status": "done", "result": {"summary_text": text}}))
    rendered = "".join(c.args[0] for c in msg.answer.call_args_list)
    assert text in rendered
    assert all(len(c.args[0].encode("utf-16-le")) // 2 <= 3500 for c in msg.answer.call_args_list)


@pytest.mark.parametrize("failure", ["timeout", "invalid_json", "wrong_shape"])
def test_legacy_chat_failure_cleans_indicators(monkeypatch, failure):
    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private-host", request=request)
        return httpx.Response(200, text="invalid" if failure == "invalid_json" else "[]")
    patch_http(monkeypatch, respond)
    monkeypatch.setattr(chat, "_chat_action_indicator", AsyncMock())
    monkeypatch.setattr(chat, "_long_request_indicator", AsyncMock())
    msg, status = message(), SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())
    msg.answer.return_value = status
    asyncio.run(chat._send_to_backend(msg, "Hello", actor_id=123))
    assert "Запрос мог быть обработан" in status.edit_text.call_args.args[0]


def test_standalone_ambiguous_start_never_falls_back_to_second_execution(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request.url.path)
        raise httpx.ReadTimeout("accepted but lost", request=request)
    patch_http(monkeypatch, respond)
    async def check():
        fsm, msg = context(), message()
        msg.from_user = SimpleNamespace(id=123, username=None, first_name="User", last_name=None)
        await fsm.update_data(agent_key="agent_strategy", agent_type="strategy", answers={})
        await agent_flow.get_task_description(msg, fsm)
        assert calls == ["/tasks/start"]
        assert await fsm.get_state() is None
        assert "проверьте /history" in msg.answer.call_args.args[0]
    asyncio.run(check())


def test_actual_dispatcher_ten_url_callbacks_execute_once(monkeypatch):
    from bot.main import create_dispatcher
    api = SimpleNamespace(execute=AsyncMock(return_value=started()))
    monkeypatch.setattr(flow, "client", api)
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=True))
    async def check():
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        user = types.User(id=123, is_bot=False, first_name="User")
        tgchat = types.Chat(id=123, type="private")
        date = datetime.now(timezone.utc)
        msg = types.Message(message_id=1, date=date, chat=tgchat, from_user=user, text="Стратегия https://own.example")
        try:
            await dp.feed_update(bot, types.Update(update_id=1, message=msg))
            fsm = dp.fsm.get_context(bot=bot, chat_id=123, user_id=123)
            pending = (await fsm.get_data())["copilot_pending"]
            payload = flow.action(pending, "own")
            async def click(index):
                query = types.CallbackQuery(id=str(index), from_user=user, chat_instance="instance", data=payload, message=msg)
                return await dp.feed_update(bot, types.Update(update_id=index, callback_query=query))
            await asyncio.gather(*(click(index) for index in range(2, 12)))
            assert api.execute.await_count == 1
            assert (await fsm.get_data())["copilot_pending"] is None
            assert (await fsm.get_data())["copilot_run"]["run_id"] == started().run_id
            await click(12)
            assert api.execute.await_count == 1
        finally:
            await bot.session.close()
            await dp.storage.close()
            await dp.fsm.events_isolation.close()
            for router in dp.sub_routers:
                router._parent_router = None
    asyncio.run(check())

@pytest.mark.parametrize("formatter,payload", [
    (agent_flow.format_analytics_details, lambda text: {"diagnosis": [text]}),
    (agent_flow.format_promo_details, lambda text: {"testing_plan": {"stop_rules": [text]}}),
    (agent_flow.format_trends_details, lambda text: {"format_trends": [{"format": text}]}),
])
def test_detailed_saved_sections_keep_tail(formatter, payload):
    text = "BEGIN" + "🚀" * 6000 + "END-SENTINEL"
    rendered = "".join(formatter(payload(text)))
    assert "END-SENTINEL" in rendered


def test_malformed_nested_saved_strategy_is_controlled():
    msg = message()
    asyncio.run(history.show_task(msg, {"agent_type": "strategy", "status": "done", "result": {"structured": {"positioning": "bad type"}}}))
    assert "Не удалось прочитать" in msg.answer.call_args.args[0]


def test_nontext_image_input_and_commands_leave_fsm_usable(monkeypatch):
    from bot.main import create_dispatcher
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=True))
    http_calls = []
    patch_http(monkeypatch, lambda request: http_calls.append(request.url.path) or httpx.Response(200, json={"items": [], "next_offset": None}))
    async def check():
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        user = types.User(id=123, is_bot=False, first_name="User")
        tgchat = types.Chat(id=123, type="private")
        date = datetime.now(timezone.utc)
        def update(mid, text=None):
            return types.Update(update_id=mid, message=types.Message(message_id=mid, date=date, chat=tgchat, from_user=user, text=text))
        try:
            fsm = dp.fsm.get_context(bot=bot, chat_id=123, user_id=123)
            await fsm.set_state(agent_flow.ImageStates.waiting_platform)
            await fsm.update_data(image_payload={})
            await dp.feed_update(bot, update(1))
            assert await fsm.get_state() == agent_flow.ImageStates.waiting_platform.state
            await dp.feed_update(bot, update(2, "/history"))
            assert http_calls == ["/projects/history"]
            await dp.feed_update(bot, update(3, "telegram"))
            await dp.feed_update(bot, update(3, "telegram"))
            assert await fsm.get_state() == agent_flow.ImageStates.waiting_use_case.state
            assert (await fsm.get_data())["image_payload"] == {"platform": "telegram"}
        finally:
            await bot.session.close()
            await dp.storage.close()
            await dp.fsm.events_isolation.close()
            for router in dp.sub_routers:
                router._parent_router = None
    asyncio.run(check())


def test_chat_sends_every_returned_image_and_continues_after_delivery_failure(monkeypatch):
    from bot.backend import BackendError
    fetch = AsyncMock(side_effect=[BackendError("failed"), b"two", b"three", b"four"])
    monkeypatch.setattr(chat, "fetch_image", fetch)
    msg = message()
    msg.answer_photo = AsyncMock()
    asyncio.run(chat._send_images_from_response(msg, {"images": [{"url": f"/images/{i}.png"} for i in range(4)]}, actor_id=123))
    assert fetch.await_count == 4
    assert msg.answer_photo.await_count == 3
    assert "Не удалось доставить" in msg.answer.call_args.args[0]


def test_image_delivery_failure_resets_fsm_without_generation_retry(monkeypatch):
    from bot.backend import BackendError
    calls = []
    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"images": [{"url": "/images/saved.png"}]})
    patch_http(monkeypatch, respond)
    monkeypatch.setattr(agent_flow, "fetch_image", AsyncMock(side_effect=BackendError("unavailable")))
    async def check():
        fsm, msg = context(), message("-")
        await fsm.update_data(image_payload={"platform": "telegram"})
        await agent_flow.image_overlay(msg, fsm)
        assert await fsm.get_state() is None
        assert calls == ["/images/generate"]
        assert "доставить его не удалось" in msg.answer.call_args.args[0]
        # Completion preserves deduplication before routing back to generic chat.
        await flow.receive(msg, fsm)
        assert calls == ["/images/generate"]
    asyncio.run(check())

@pytest.mark.parametrize("row", [
    {"id": 1, "agent_type": [], "created_at": "now", "task_description": "x"},
    {"id": "bad", "agent_type": "strategy", "created_at": "now", "task_description": "x"},
    {"id": 1, "agent_type": "strategy", "created_at": "now", "task_description": {}},
])
def test_malformed_history_rows_are_controlled(monkeypatch, row):
    patch_http(monkeypatch, lambda request: httpx.Response(200, json=[row]))
    msg = message("/history")
    asyncio.run(history.cmd_history(msg))
    assert "Не удалось получить историю" in msg.answer.call_args.args[0]


@pytest.mark.parametrize("response", [
    {"status": "need_info", "session_id": "s", "questions": [{"key": "product"}]},
    {"status": "need_info", "session_id": "s", "questions": [{"key": [], "question": "Product?"}]},
    {"status": "need_info", "session_id": "s", "questions": []},
    {"status": "done", "result": []},
    [],
])
def test_malformed_standalone_responses_are_controlled(monkeypatch, response):
    patch_http(monkeypatch, lambda request: httpx.Response(200, json=response))
    async def check():
        fsm, msg = context(), message()
        msg.from_user = SimpleNamespace(id=123, username=None, first_name="User", last_name=None)
        await fsm.update_data(agent_key="agent_strategy", agent_type="strategy", answers={})
        await agent_flow.get_task_description(msg, fsm)
        assert await fsm.get_state() is None
        assert "Не удалось подтвердить запуск" in msg.answer.call_args.args[0]
    asyncio.run(check())
