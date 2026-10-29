"""Offline lifecycle transport permits only the explicit private command menu."""
import asyncio

import pytest
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import SendMessage, SetMyCommands
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats

from bot.main import register_commands
from tests.release_offline_bot import offline_request


def test_actual_command_startup_uses_allowed_offline_private_scope(monkeypatch):
    captured = []
    async def request(self, bot, method, timeout=None):
        captured.append(method)
        return await offline_request(self, bot, method, timeout)
    monkeypatch.setattr(AiohttpSession, "make_request", request)
    async def check():
        async with Bot("123456:offline-token") as bot:
            await register_commands(bot)
        assert len(captured) == 1 and isinstance(captured[0], SetMyCommands)
    asyncio.run(check())


@pytest.mark.parametrize("method", [
    SetMyCommands(commands=[BotCommand(command="menu", description="Menu")]),
    SetMyCommands(commands=[BotCommand(command="unapproved", description="Unapproved")],
        scope=BotCommandScopeAllPrivateChats()),
    SendMessage(chat_id=123, text="unapproved"),
])
def test_offline_transport_still_rejects_unapproved_telegram_actions(method):
    with pytest.raises(AssertionError):
        asyncio.run(offline_request(None, None, method))
