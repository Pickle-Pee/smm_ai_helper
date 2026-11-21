"""Control commands remain responsive without releasing execution isolation."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, types

from bot import copilot_flow as flow
from tests.test_telegram_copilot import started
from tests.test_telegram_navigation_fixtures import no_selected_project

pytestmark = pytest.mark.usefixtures("no_selected_project")


@pytest.mark.parametrize("command", ["/new", "/cancel"])
def test_control_command_during_slow_request_and_other_user(monkeypatch, command):
    from bot.main import create_dispatcher
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "__call__", sent)
    from bot import backend
    monkeypatch.setattr(backend, "request", AsyncMock(return_value={"version": 1, "active": None}))
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def execute(actor, payload):
            calls.append(actor)
            if actor == 123:
                entered.set()
                await release.wait()
            return started()
        monkeypatch.setattr(flow.client, "execute", execute)
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        def update(mid, actor, text):
            return types.Update(update_id=mid, message=types.Message(message_id=mid,
                date=datetime.now(timezone.utc), chat=types.Chat(id=actor, type="private"),
                from_user=types.User(id=actor, is_bot=False, first_name="User"), text=text))
        running = asyncio.create_task(dp.feed_update(bot, update(1, 123, "Стратегия")))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await asyncio.wait_for(dp.feed_update(bot, update(2, 123, command)), 2)
            assert not running.done()
            assert any("Предыдущий запрос" in str(call.args) for call in sent.call_args_list)
            await asyncio.wait_for(dp.feed_update(bot, update(3, 456, "Стратегия")), 2)
            assert calls == [123, 456]
            release.set()
            await running
            state = dp.fsm.get_context(bot=bot, chat_id=123, user_id=123)
            assert (await state.get_data())["copilot_run"]["run_id"] == started().run_id
            await dp.feed_update(bot, update(4, 123, "/new"))
            assert await state.get_state() is None
            guard = next(m for m in dp.update.outer_middleware if hasattr(m, "counts"))
            assert guard.counts == {}
        finally:
            release.set()
            await asyncio.gather(running, return_exceptions=True)
            await bot.session.close()
            await dp.storage.close()
            await dp.fsm.events_isolation.close()
            for router in dp.sub_routers:
                router._parent_router = None
    asyncio.run(check())


def test_polling_shutdown_waits_for_update_and_delivery_before_closing(monkeypatch):
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.methods import GetMe, GetUpdates
    from tests.test_telegram_navigation import update

    import bot.delivery as delivery
    import bot.main as runtime

    monkeypatch.setattr(runtime, "setup_logging", lambda: None)
    monkeypatch.setattr(runtime, "validate_configuration", lambda: None)
    monkeypatch.setattr(runtime.settings, "TELEGRAM_BOT_TOKEN", "123456:offline-token")

    async def run():
        dp = runtime.DrainingDispatcher()
        monkeypatch.setattr(runtime, "create_dispatcher", lambda: dp)
        update_started, delivery_started = asyncio.Event(), asyncio.Event()
        release_update, release_delivery = asyncio.Event(), asyncio.Event()
        events = []
        polled = False

        async def request(self, bot, method, timeout=None):
            nonlocal polled
            if isinstance(method, GetMe):
                return types.User(id=bot.id, first_name="Offline", is_bot=True)
            if isinstance(method, GetUpdates):
                if not polled:
                    polled = True
                    return [update(1, "slow")]
                await asyncio.Event().wait()
            raise AssertionError(type(method))

        async def handler(message):
            update_started.set()
            await release_update.wait()
            events.append("update_finished")

        async def deliver(bot, client):
            assert not delivery_started.is_set()
            delivery_started.set()
            await release_delivery.wait()
            events.append("delivery_acked")
            return True

        async def close(self):
            events.append("session_closed")

        dp.message.register(handler)
        dp.shutdown.register(lambda: events.append("fsm_shutdown"))
        monkeypatch.setattr(AiohttpSession, "make_request", request)
        monkeypatch.setattr(AiohttpSession, "close", close)
        monkeypatch.setattr(delivery, "deliver_once", deliver)
        running = asyncio.create_task(runtime.main())
        try:
            await asyncio.wait_for(update_started.wait(), 2)
            await asyncio.wait_for(delivery_started.wait(), 2)
            stopping = asyncio.create_task(dp.stop_polling())
            await asyncio.wait_for(dp.delivery_stop.wait(), 2)
            assert not running.done() and not stopping.done() and not events
            release_update.set()
            await asyncio.wait_for(stopping, 2)
            assert events == ["update_finished", "fsm_shutdown"]
            assert not running.done()
            release_delivery.set()
            await asyncio.wait_for(running, 2)
            assert events == ["update_finished", "fsm_shutdown", "delivery_acked", "session_closed"]
        finally:
            release_update.set()
            release_delivery.set()
            if not running.done():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)

    asyncio.run(run())


def test_guard_drains_active_update_cleanup_before_resource_close():
    from types import SimpleNamespace
    from bot.operation_guard import OperationGuard
    async def check():
        guard = OperationGuard()
        entered = asyncio.Event()
        cleanup = []
        async def handler(event, data):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleanup.append("cleaned")
        msg = SimpleNamespace(from_user=SimpleNamespace(id=1), chat=SimpleNamespace(id=1, type="private"), text="Task")
        task = asyncio.create_task(guard(handler, SimpleNamespace(message=msg, callback_query=None), {}))
        await entered.wait()
        await guard.close()
        assert task.cancelled() and cleanup == ["cleaned"]
        assert not guard.tasks and not guard.counts
    asyncio.run(check())


@pytest.mark.parametrize("command", ["/new", "/cancel"])
def test_guard_drains_slow_busy_command_response_before_session_close(monkeypatch, command):
    """Busy control replies are owned tasks even though they bypass FSM handling."""
    from types import SimpleNamespace
    import bot.operation_guard as operation_guard

    async def check():
        guard = operation_guard.OperationGuard()
        execution_entered, sending_entered = asyncio.Event(), asyncio.Event()
        cleanup = []

        async def handler(event, data):
            try:
                execution_entered.set()
                await asyncio.Event().wait()
            finally:
                cleanup.append("execution_stopped")

        async def slow_send(message, text):
            try:
                sending_entered.set()
                await asyncio.Event().wait()
            finally:
                cleanup.append("busy_send_stopped")

        monkeypatch.setattr(operation_guard, "send_text", slow_send)

        def event(text):
            msg = SimpleNamespace(from_user=SimpleNamespace(id=1),
                chat=SimpleNamespace(id=1, type="private"), text=text)
            return SimpleNamespace(message=msg, callback_query=None)

        executing = asyncio.create_task(guard(handler, event("Task"), {}))
        busy = None
        try:
            await asyncio.wait_for(execution_entered.wait(), 1)
            busy = asyncio.create_task(guard(handler, event(command), {}))
            await asyncio.wait_for(sending_entered.wait(), 1)
            assert guard.tasks == {executing, busy}
            await asyncio.wait_for(guard.close(), 1)
            cleanup.append("session_closed")
            assert executing.cancelled() and busy.cancelled()
            assert cleanup.index("execution_stopped") < cleanup.index("session_closed")
            assert cleanup.index("busy_send_stopped") < cleanup.index("session_closed")
            assert not guard.tasks and not guard.counts
        finally:
            for task in (executing, busy):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (executing, busy) if task is not None), return_exceptions=True)

    asyncio.run(check())
