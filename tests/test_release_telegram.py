"""Restart/replay guarantees through the actual Telegram HTTP adapter."""
import asyncio
from types import SimpleNamespace
import uuid
from unittest.mock import AsyncMock

import pytest

from app.marketing_copilot.contracts import IntentKind
from bot import copilot_flow as flow
from bot.copilot_client import CopilotError
from bot.handlers.copilot import recent_runs, earlier_runs, check_status
from tests.postgresql_support import mvp_database
from tests.test_copilot_api_postgresql import CONTEXT, configured, remove_actor
from tests.test_graph_postgresql import state as graph_state
from tests.test_release_hardening_postgresql import drain
from tests.test_strategy_builder import StrategyModel
from tests.test_telegram_copilot import message, context, click, text_sent
from tests.test_telegram_copilot_postgresql import wire, brand


@pytest.mark.parametrize("failure", ["crash_before_ack", "timeout_after_accept"])
def test_acceptance_survives_lost_ack_and_redelivery(mvp_database, monkeypatch, failure):
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=StrategyModel(use_parents=True))
        calls = wire(monkeypatch, api)
        await brand(mvp_database, actor, CONTEXT)
        msg, fsm = message(actor=actor), context(actor)
        original = flow.client.execute
        accepted = []
        async def interrupted(actor, payload):
            result = await original(actor, payload)
            accepted.append(result.run_id)
            if len(accepted) == 1:
                if failure == "crash_before_ack":
                    raise asyncio.CancelledError()
                raise CopilotError("unavailable")
            return result
        flow.client.execute = interrupted
        try:
            if failure == "crash_before_ack":
                with pytest.raises(asyncio.CancelledError):
                    await flow.receive(msg, fsm)
                assert not msg.answer.called
            else:
                await flow.receive(msg, fsm)
                assert "Не удалось связаться" in text_sent(msg)
                callback = await click(fsm, msg, "retry", "redelivered-callback", actor)
                await fsm.update_data(copilot_seen=[])
                await flow.callback_action(callback, fsm)  # Even without event ledger: stale/finalized callback.
                assert len(calls) == 2
            rid = accepted[0]
            # Restart discards *all* FSM data, including latest-run pointer.
            restarted = context(actor)
            listing = message("/copilot_runs", actor=actor)
            await recent_runs(listing)
            markup = listing.answer.call_args.kwargs["reply_markup"]
            assert markup.inline_keyboard[0][0].callback_data == flow.run_callback(rid)
            assert not await restarted.get_data()
            # Duplicate message after loss of the local ledger uses the same backend key.
            await flow.receive(msg, restarted)
            assert set(accepted) == {rid} and len({p.request_key for p in calls}) == 1
            assert len((await graph_state(mvp_database, rid))[1]) == 1
            await drain(api, mvp_database, rid)
            result = message(actor=actor)
            cb = SimpleNamespace(data=flow.run_callback(rid), from_user=SimpleNamespace(id=actor),
                                 message=result, answer=AsyncMock())
            await check_status(cb)
            assert "Стратегический диагноз" in text_sent(result) and "Эксперименты" in text_sent(result)
            await check_status(cb)  # Replay presentation; no generation or new artifacts.
            _, jobs, artifacts = await graph_state(mvp_database, rid)
            assert len(jobs) == len(artifacts) == 3
            foreign = message("/copilot_runs", actor=actor + 1)
            await recent_runs(foreign)
            assert "пока нет" in text_sent(foreign)
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_restart_pre_run_callbacks_fail_closed_even_after_same_update_redelivery(monkeypatch):
    client = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(flow, "client", client)
    async def check():
        msg, original = message("Собери стратегию https://own.example"), context()
        await flow.receive(msg, original)
        old = (await original.get_data())["copilot_pending"]
        callback = SimpleNamespace(data=flow.action(old, "own"), id="old", message=msg,
                                   from_user=msg.from_user, answer=AsyncMock())
        restarted = context()
        await flow.callback_action(callback, restarted)
        assert "устарело" in callback.answer.call_args.args[0]
        await flow.receive(msg, restarted)
        new = (await restarted.get_data())["copilot_pending"]
        assert old["payload"]["request_key"] == new["payload"]["request_key"]
        assert old["token"] != new["token"]
        await flow.callback_action(callback, restarted)
        assert "устарело" in callback.answer.call_args.args[0]
        assert not new["payload"].get("owned_site_url")
        client.execute.assert_not_awaited()
    asyncio.run(check())


def test_list_private_scope_pagination_and_safe_errors(monkeypatch):
    client = SimpleNamespace(recent=AsyncMock(side_effect=CopilotError("temporary")))
    monkeypatch.setattr(flow, "client", client)
    async def check():
        msg = message("/copilot_runs")
        msg.chat.type = "group"
        await recent_runs(msg)
        client.recent.assert_not_awaited()
        msg.chat.type = "private"
        cb = SimpleNamespace(data="cr:10", from_user=SimpleNamespace(id=321), message=msg, answer=AsyncMock())
        await earlier_runs(cb)
        client.recent.assert_awaited_once_with(321, offset=10)
        assert "временно недоступен" in text_sent(msg)
        for bad in ("cr:-1", "cr:10001", "cr:abc", "cr:00"):
            cb.data = bad
            await earlier_runs(cb)
        assert client.recent.await_count == 1
    asyncio.run(check())
