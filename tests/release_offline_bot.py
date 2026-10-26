"""Real bot lifecycle/Dispatcher signals, with Telegram transport disabled."""
import asyncio

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import GetMe, GetUpdates, SetMyCommands
from aiogram.types import User, BotCommandScopeAllPrivateChats

from bot.main import main


async def offline_request(self, bot, method, timeout=None):
    if isinstance(method, GetMe):
        return User(id=123456, is_bot=True, first_name="Offline", username="offline_bot")
    if isinstance(method, SetMyCommands):
        assert isinstance(method.scope, BotCommandScopeAllPrivateChats)
        assert [command.command for command in method.commands] == [
            "menu", "new", "history", "active", "case_history", "cancel", "help"]
        assert all(command.description for command in method.commands)
        return True
    if isinstance(method, GetUpdates):
        print("OFFLINE_TELEGRAM_POLL_READY", flush=True)
        await asyncio.Event().wait()
    raise AssertionError("Unapproved Telegram method in offline lifecycle probe")


if __name__ == "__main__":
    AiohttpSession.make_request = offline_request
    asyncio.run(main())
