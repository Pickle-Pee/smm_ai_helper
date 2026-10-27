"""Read-only recovery of synchronous receipts after local state loss."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram import Bot, types

from bot import copilot_contracts as dto, copilot_flow as flow
from bot.copilot_client import CopilotClient, CopilotError
from bot.handlers.copilot import saved_result
from tests.test_telegram_copilot import context, message, patch_http, text_sent


def post_response():
    return dto.ModuleResponse(result=dto.Post(headline="Saved headline", body="Saved case-specific body", cta="Saved CTA"))


def test_client_gets_owner_scoped_receipt_without_post(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=post_response().model_dump(mode="json"))
    patch_http(monkeypatch, respond)
    result = asyncio.run(CopilotClient().saved_execution(321, "tg:321:321:8"))
    assert result.result.body == "Saved case-specific body"
    assert len(calls) == 1 and calls[0].method == "GET"
    assert calls[0].url.path == "/copilot/executions/tg:321:321:8"
    assert calls[0].headers["x-telegram-user-id"] == "321"


@pytest.mark.parametrize("key", ["../other", "", "a" * 129, "space key"])
def test_client_invalid_key_never_calls_network(monkeypatch, key):
    request = AsyncMock()
    client = CopilotClient()
    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(CopilotError):
        asyncio.run(client.saved_execution(321, key))
    request.assert_not_awaited()


def test_recovery_uses_message_actor_and_no_fsm_or_generation(monkeypatch):
    api = SimpleNamespace(saved_execution=AsyncMock(return_value=post_response()), execute=AsyncMock())
    monkeypatch.setattr(flow, "client", api)
    msg = message("/copilot_result tg:123:123:1", actor=456)
    asyncio.run(saved_result(msg))
    api.saved_execution.assert_awaited_once_with(456, "tg:123:123:1")
    api.execute.assert_not_awaited()
    assert "Saved case-specific body" in text_sent(msg)


def test_conversation_receipt_does_not_regenerate_legacy_chat(monkeypatch):
    api = SimpleNamespace(saved_execution=AsyncMock(return_value=dto.ConversationResponse()), execute=AsyncMock())
    monkeypatch.setattr(flow, "client", api)
    from bot.handlers import chat
    generate = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", generate)
    msg = message("/copilot_result old-key")
    asyncio.run(saved_result(msg))
    generate.assert_not_awaited()
    api.execute.assert_not_awaited()
    assert "Сохранённого ответа Copilot" in text_sent(msg)


def test_unknown_request_surfaces_recovery_key(monkeypatch):
    async def check():
        state = context()
        msg = message()
        pending = dict(payload={"request_key": "tg:123:123:1"}, nonce="nonce", revision=0)
        await flow.error(msg, state, pending, CopilotError("unavailable"))
        assert "/copilot_result tg:123:123:1" in text_sent(msg)
        assert "30 дней" in text_sent(msg)
    asyncio.run(check())


def test_real_dispatcher_recovery_command_after_storage_restart(monkeypatch):
    from bot.main import create_dispatcher
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "__call__", sent)
    api = SimpleNamespace(saved_execution=AsyncMock(return_value=post_response()), execute=AsyncMock())
    monkeypatch.setattr(flow, "client", api)
    async def check():
        dispatcher, bot = create_dispatcher(), Bot("123456:offline-recovery")
        try:
            msg = types.Message(message_id=1, date=datetime.now(timezone.utc),
                chat=types.Chat(id=123, type="private"),
                from_user=types.User(id=123, is_bot=False, first_name="User"),
                text="/copilot_result tg:123:123:1")
            await dispatcher.feed_update(bot, types.Update(update_id=1, message=msg))
            api.saved_execution.assert_awaited_once_with(123, "tg:123:123:1")
            api.execute.assert_not_awaited()
            assert any("Saved case-specific body" in str(call) for call in sent.call_args_list)
        finally:
            await bot.session.close()
            await dispatcher.storage.close()
            await dispatcher.fsm.events_isolation.close()
            for router in dispatcher.sub_routers:
                router._parent_router = None
    asyncio.run(check())
