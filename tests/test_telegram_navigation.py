"""Dispatcher and transport regressions for durable Telegram project selection."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from aiogram import Bot, types

from bot import backend, project_navigation as nav
from bot.handlers import chat, mentor
from tests.test_telegram_copilot import context, message, text_sent, RID


def item(public_id="g:" + RID, title="Стратегия — Бизнес A"):
    kind, source_id = public_id.split(":", 1)
    return {"public_id": public_id, "source_type": {"g": "graph", "w": "workflow", "t": "task", "r": "receipt", "l": "legacy", "c": "conversation"}[kind],
        "source_id": source_id, "title": title, "short_description": "Сохранённый бизнес A",
        "created_at": "2026-10-22T12:00:00+00:00", "last_activity_at": "2026-10-26T12:00:00+00:00",
        "status": "completed", "capabilities": ["view_result", "resume_conversation", "view_history", "start_new_from_source"]}


def click(data, actor=123):
    return SimpleNamespace(data=data, id="click", message=message(actor=actor),
        from_user=SimpleNamespace(id=actor), answer=AsyncMock())


class OfflineProjects:
    def __init__(self):
        self.version, self.active = 0, None
        self.calls, self.generations = [], []
        self.catalog = {"g:" + RID: item(), "g:" + "cd" * 32: item("g:" + "cd" * 32, "Стратегия — Бизнес B")}

    async def request(self, method, path, actor, *, payload=None):
        self.calls.append((method, path, actor, payload))
        if path == f"/brand-profile/{actor}":
            return {"brand_name": "Бизнес A", "product_description": "Продукт A", "audience": "Аудитория A", "goals": ["Цель A"]}
        if path.startswith("/projects/context?"):
            return {"version": self.version, "active": self.active}
        if method == "POST" and path == "/projects/context":
            if payload["expected_version"] != self.version: raise backend.BackendError("stale")
            self.active = self.catalog[payload["public_id"]] if payload["public_id"] else None
            self.version += 1
            return {"version": self.version, "active": self.active, "restored_components": ["сохранённая стратегия"]}
        if method == "POST" and path == "/projects/context/messages":
            assert payload["expected_version"] == self.version
            self.generations.append((self.active["public_id"], payload))
            return {"reply": "Ответ о " + self.active["title"], "public_id": self.active["public_id"], "session_id": "session"}
        if path.startswith("/projects/history?"):
            return {"items": list(self.catalog.values()), "next_offset": 8}
        if path.startswith("/projects/items/"):
            public_id = path.removeprefix("/projects/items/")
            if "/discussion" in public_id:
                return {"public_id": public_id.split("/discussion")[0], "turns": [], "next_offset": None}
            return {**self.catalog[public_id], "goal": "Привлечь клиентов A", "context_description": "Бизнес A",
                    "artifacts": ["Стратегия"], "result": None}
        raise AssertionError((method, path, actor, payload))


def update(mid, text, *, actor=123, chat_id=None, chat_type="private"):
    return types.Update(update_id=mid, message=types.Message(message_id=mid,
        date=datetime.now(timezone.utc), chat=types.Chat(id=actor if chat_id is None else chat_id, type=chat_type),
        from_user=types.User(id=actor, is_bot=False, first_name="User"), text=text))


async def close_dispatcher(dp, bot):
    await dp["operation_guard"].close()
    await bot.session.close()
    await dp.storage.close()
    await dp.fsm.events_isolation.close()
    for router in dp.sub_routers: router._parent_router = None


def test_start_all_menu_buttons_override_pending_state_without_generation(monkeypatch):
    from bot.main import create_dispatcher
    sent, llm = AsyncMock(return_value=True), AsyncMock()
    fake = OfflineProjects()
    monkeypatch.setattr(Bot, "__call__", sent)
    monkeypatch.setattr(backend, "request", fake.request)
    monkeypatch.setattr(chat, "receive", llm)
    async def check():
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        state = dp.fsm.get_context(bot=bot, chat_id=123, user_id=123)
        try:
            for mid, text in enumerate(["/start", nav.HISTORY, nav.CONTEXT, nav.PROFILE, nav.HELP, nav.BACK], 1):
                await state.set_state("AnyForm:any_step")
                await dp.feed_update(bot, update(mid, text))
            assert any(isinstance(call.args[0].reply_markup, types.ReplyKeyboardMarkup) for call in sent.call_args_list)
            llm.assert_not_awaited()
            assert not fake.generations
            assert all(method == "GET" for method, *_ in fake.calls)
        finally: await close_dispatcher(dp, bot)
    asyncio.run(check())


@pytest.mark.parametrize("public_id", ["g:" + RID, "w:" + "ab" * 16, "r:" + RID, "t:123", "l:chat", "c:0", "c:31"])
def test_canonical_callbacks_fit_telegram_even_maximum_binding_version(public_id):
    data = nav.callback("a", public_id, 2**63 - 2)
    assert len(data.encode()) <= 64
    assert nav.unpack(data.split(":")[2]) == public_id
    assert int(data.split(":")[3], 36) == 2**63 - 2


def test_card_is_read_only_and_stale_activation_cannot_switch_back(monkeypatch):
    fake = OfflineProjects()
    monkeypatch.setattr(backend, "request", fake.request)
    async def check():
        msg, state = message(), context()
        await nav.show_card(msg, 123, "g:" + RID)
        assert all(method == "GET" for method, *_ in fake.calls)
        first = nav.callback("a", "g:" + RID, 0)
        await nav.navigation_callback(click(first), state)
        assert fake.active["source_id"] == RID
        await nav.navigation_callback(click(nav.callback("a", "g:" + "cd" * 32, 1)), state)
        assert fake.active["source_id"] == "cd" * 32
        stale = click(first)
        await nav.navigation_callback(stale, state)
        assert fake.active["source_id"] == "cd" * 32
        assert "устарело" in text_sent(stale.message)
        assert fake.generations == []
    asyncio.run(check())


def test_restart_dispatcher_reads_durable_selection_and_routes_followups(monkeypatch):
    from bot.main import create_dispatcher
    fake, sent, llm = OfflineProjects(), AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(backend, "request", fake.request)
    monkeypatch.setattr(Bot, "__call__", sent)
    monkeypatch.setattr(chat, "receive", llm)
    async def check():
        for index, public_id in enumerate(["g:" + RID, "g:" + "cd" * 32]):
            await fake.request("POST", "/projects/context", 123, payload={"chat_id": 123, "expected_version": index, "public_id": public_id})
            # New dispatcher and MemoryStorage simulate a process restart; only
            # the backend fake retains the selected project.
            dp, bot = create_dispatcher(), Bot("123456:offline-token")
            try: await dp.feed_update(bot, update(index + 10, "Какая аудитория?"))
            finally: await close_dispatcher(dp, bot)
        assert [entry[0] for entry in fake.generations] == ["g:" + RID, "g:" + "cd" * 32]
        assert fake.generations[0][1]["request_key"] == "tg:123:123:10"
        llm.assert_not_awaited()
    asyncio.run(check())


def test_context_lookup_failure_never_falls_through_to_new_copilot(monkeypatch):
    from bot.main import create_dispatcher
    sent, llm = AsyncMock(return_value=True), AsyncMock()
    monkeypatch.setattr(Bot, "__call__", sent)
    monkeypatch.setattr(backend, "request", AsyncMock(side_effect=backend.BackendError("hidden")))
    monkeypatch.setattr(chat, "receive", llm)
    async def check():
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        try:
            await dp.feed_update(bot, update(1, "Продолжи"))
            llm.assert_not_awaited()
            assert any("не запускается" in str(call.args) for call in sent.call_args_list)
        finally: await close_dispatcher(dp, bot)
    asyncio.run(check())


@pytest.mark.parametrize("body", [{"version": 0}, {"version": True, "active": None},
    {"version": 0, "active": {}}, {"version": -1, "active": None}])
def test_malformed_binding_cannot_silently_route_into_unrelated_chat(monkeypatch, body):
    from bot.main import create_dispatcher
    llm = AsyncMock()
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=True))
    monkeypatch.setattr(backend, "request", AsyncMock(return_value=body))
    monkeypatch.setattr(chat, "receive", llm)
    async def check():
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        try:
            await dp.feed_update(bot, update(1, "Продолжи прежний проект"))
            llm.assert_not_awaited()
        finally: await close_dispatcher(dp, bot)
    asyncio.run(check())


def test_new_request_clears_fsm_only_after_confirmed_backend_deactivation(monkeypatch):
    fake = OfflineProjects()
    monkeypatch.setattr(backend, "request", fake.request)
    async def check():
        msg, state = message(nav.NEW), context()
        await state.set_state("AnyForm:any_step")
        await state.update_data(mentor_run_id=RID)
        await nav.navigate(msg, state)
        assert await state.get_state() is None
        assert await state.get_data() == {}
        assert fake.version == 1 and fake.active is None
        await state.set_state("AnyForm:any_step")
        monkeypatch.setattr(backend, "request", AsyncMock(side_effect=backend.BackendError("offline")))
        await nav.navigate(msg, state)
        assert await state.get_state() == "AnyForm:any_step"
    asyncio.run(check())


def test_confirmed_context_switch_invalidates_old_global_action_tokens(monkeypatch):
    fake = OfflineProjects()
    monkeypatch.setattr(backend, "request", fake.request)
    chat.ACTION_STORE["123"] = {"old": "Старый prompt"}
    chat.ACTION_EXPIRES["123"] = __import__("time").monotonic() + 1000
    asyncio.run(nav.navigation_callback(click(nav.callback("a", "g:" + RID, 0)), context()))
    assert "123" not in chat.ACTION_STORE and "123" not in chat.ACTION_EXPIRES


def test_old_standalone_buttons_cannot_install_misleading_fsm_over_active_project(monkeypatch):
    from bot.handlers.agent_flow import choose_agent, choose_image
    fake = OfflineProjects()
    fake.active = item()
    monkeypatch.setattr(backend, "request", fake.request)
    async def check():
        state = context()
        for handler, data in [(choose_agent, "agent_strategy"), (choose_image, "generate_image")]:
            event = click(data)
            await handler(event, state)
            assert await state.get_state() is None
            assert "Новый запрос" in str(event.answer.call_args)
        assert not fake.generations
    asyncio.run(check())


def test_group_and_wrong_private_chat_never_read_or_activate_context(monkeypatch):
    from bot.main import create_dispatcher
    calls, sent = AsyncMock(), AsyncMock(return_value=True)
    monkeypatch.setattr(backend, "request", calls)
    monkeypatch.setattr(Bot, "__call__", sent)
    async def check():
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        try:
            await dp.feed_update(bot, update(1, nav.HISTORY, chat_id=-10, chat_type="group"))
            await dp.feed_update(bot, update(2, nav.HISTORY, chat_id=456))
            callback = click(nav.callback("a", "g:" + RID, 0))
            callback.message.chat.type = "group"
            await nav.navigation_callback(callback, context())
            calls.assert_not_awaited()
        finally: await close_dispatcher(dp, bot)
    asyncio.run(check())


def test_history_page_filter_and_search_use_bounded_backend_projection(monkeypatch):
    fake = OfflineProjects()
    monkeypatch.setattr(backend, "request", fake.request)
    async def check():
        msg, state = message(), context()
        await nav.show_history(msg, 123, offset=8, source="task", status="failed")
        query = parse_qs(urlsplit(fake.calls[-1][1]).query)
        assert query == {"limit": ["8"], "offset": ["8"], "source_type": ["task"], "status": ["failed"]}
        assert msg.answer.await_count == 1
        await state.set_state(nav.NavigationStates.search)
        await nav.form_input(message("Stretch Point"), state)
        assert parse_qs(urlsplit(fake.calls[-1][1]).query)["query"] == ["Stretch Point"]
        assert not fake.generations
    asyncio.run(check())


def test_legacy_view_renders_actual_saved_messages_without_project_session(monkeypatch):
    card = {**item("l:chat", "Архив общего чата"), "capabilities": ["view_result"],
        "result": {"messages": [{"role": "user" if i % 2 == 0 else "assistant", "text": f"Архивное сообщение {i}"}
                                for i in range(18)], "older_messages_omitted": True}}
    async def request(method, path, actor, *, payload=None):
        assert method == "GET" and path == "/projects/items/l:chat" and actor == 123
        return card
    captured = AsyncMock(side_effect=request)
    monkeypatch.setattr(backend, "request", captured)
    async def check():
        event = click(nav.callback("v", "l:chat"))
        await nav.navigation_callback(event, context())
        text = text_sent(event.message)
        assert "Архивное сообщение 17" in text and "Архивное сообщение 10" in text
        assert "Архивное сообщение 9" not in text
        assert "не разделены по проектам" in text and "последними 50" in text
        older = event.message.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data
        page = click(older)
        await nav.navigation_callback(page, context())
        assert "Архивное сообщение 9" in text_sent(page.message)
        assert "Архивное сообщение 17" not in text_sent(page.message)
        assert captured.await_count == 2  # Never calls the empty project-discussion endpoint.
    asyncio.run(check())


def test_profile_menu_displays_saved_fields_and_no_generation(monkeypatch):
    fake = OfflineProjects()
    monkeypatch.setattr(backend, "request", fake.request)
    async def check():
        msg = message(nav.PROFILE)
        await nav.navigate(msg, context())
        assert "Название: Бизнес A" in text_sent(msg)
        assert "Продукт: Продукт A" in text_sent(msg)
        assert "Аудитория: Аудитория A" in text_sent(msg)
        assert "Цели: Цель A" in text_sent(msg)
        assert fake.calls == [("GET", "/brand-profile/123", 123, None)]
        assert not fake.generations
    asyncio.run(check())


def test_legacy_explanation_is_read_only_and_does_not_replace_active_selection(monkeypatch):
    from tests.test_telegram_case_mentor import explanation
    request = AsyncMock(return_value=explanation())
    monkeypatch.setattr(backend, "request", request)
    async def check():
        state, msg = context(), message()
        await state.update_data(mentor_run_id="cd" * 32)
        await mentor.show_case(msg, 123, RID, state)
        assert (await state.get_data())["mentor_run_id"] == "cd" * 32
        assert await state.get_state() is None
        assert request.await_count == 1
        assert "Открыть карточку проекта" in str(msg.answer.call_args_list[-1].kwargs)
    asyncio.run(check())


def test_legacy_global_chat_action_cannot_bypass_selected_project(monkeypatch):
    fake, legacy = OfflineProjects(), AsyncMock()
    fake.active = item()
    monkeypatch.setattr(backend, "request", fake.request)
    monkeypatch.setattr(chat, "_send_to_backend", legacy)
    chat.ACTION_STORE["123"] = {"token": "Старый глобальный запрос"}
    chat.ACTION_EXPIRES["123"] = __import__("time").monotonic() + 1000
    async def check():
        event = click("action:token")
        await chat.on_action(event)
        legacy.assert_not_awaited()
        assert "старому чату" in str(event.answer.call_args)
    asyncio.run(check())


def test_global_action_has_durable_callback_identity_distinct_from_bot_message(monkeypatch):
    fake, send = OfflineProjects(), AsyncMock()
    monkeypatch.setattr(backend, "request", fake.request)
    monkeypatch.setattr(chat, "_send_to_backend", send)
    token = chat._actions_keyboard(123, [{"text": "Проверить CPL"}]).inline_keyboard[0][0].callback_data
    event = click(token)
    event.id = "telegram-callback-42"
    asyncio.run(chat.on_action(event))
    expected = "tg:123:123:action:" + __import__("hashlib").sha256(event.id.encode()).hexdigest()[:32]
    assert send.call_args.kwargs["request_key"] == expected


def test_read_only_history_menu_stays_responsive_during_project_generation(monkeypatch):
    from bot.main import create_dispatcher
    fake, sent = OfflineProjects(), AsyncMock(return_value=True)
    fake.active = item()
    entered, release = None, None
    async def request(method, path, actor, *, payload=None):
        if path == "/projects/context/messages":
            entered.set()
            await release.wait()
        return await fake.request(method, path, actor, payload=payload)
    monkeypatch.setattr(backend, "request", request)
    monkeypatch.setattr(Bot, "__call__", sent)
    async def check():
        nonlocal entered, release
        entered, release = asyncio.Event(), asyncio.Event()
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        running = asyncio.create_task(dp.feed_update(bot, update(1, "Объясни")))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await asyncio.wait_for(dp.feed_update(bot, update(2, nav.HISTORY)), 2)
            assert not running.done()
            assert any("Проекты и история" in str(call.args) for call in sent.call_args_list)
            release.set()
            await running
            assert len(fake.generations) == 1
        finally:
            release.set()
            await asyncio.gather(running, return_exceptions=True)
            await close_dispatcher(dp, bot)
    asyncio.run(check())


def test_conversation_callback_keeps_original_user_update_identity(monkeypatch):
    from bot import copilot_contracts as dto, copilot_flow as flow
    original_key = "tg:123:123:17"
    send = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", send)
    monkeypatch.setattr(flow, "client", SimpleNamespace(execute=AsyncMock(return_value=dto.ConversationResponse())))
    async def check():
        state = context()
        pending = {"payload": {"request_key": original_key, "message": "Обсудим продвижение"},
            "nonce": "nonce", "revision": 0}
        bot_message = message(mid=900)
        await flow.execute(bot_message, 123, state, pending)
        assert send.call_args.kwargs["request_key"] == original_key
        assert send.call_args.kwargs["request_key"] != "tg:123:123:900"
    asyncio.run(check())


@pytest.mark.parametrize("public_id", ["t:2147483648", "c:9223372036854775808"])
def test_oversized_database_identities_cannot_be_encoded_as_callbacks(public_id):
    with pytest.raises(ValueError):
        nav.pack(public_id)
