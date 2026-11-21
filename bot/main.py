# bot/main.py
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation
from app.config import settings
from app.logging import setup_logging
from bot.backend import validate_configuration
from bot.handlers import menu, agent_flow, history, chat, workflow, copilot, mentor
from bot.delivery import delivery_loop
from bot.operation_guard import OperationGuard
from bot.project_navigation import context_router


log = logging.getLogger(__name__)


class DrainingDispatcher(Dispatcher):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.delivery_stop = asyncio.Event()

    async def emit_shutdown(self, *args, **kwargs):
        # Aiogram stops the poller before emitting shutdown, but still owns
        # the dispatched update tasks. Keep FSM and Telegram alive until done.
        self.delivery_stop.set()
        await asyncio.gather(*tuple(self._handle_update_tasks), return_exceptions=True)
        await super().emit_shutdown(*args, **kwargs)


def create_dispatcher():
    # Serialize a user's message/callback FSM updates, including HTTP awaits.
    dp = DrainingDispatcher(events_isolation=SimpleEventIsolation(), disable_fsm=True)
    guard = OperationGuard()
    dp["operation_guard"] = guard
    dp.update.outer_middleware(guard)
    dp.update.outer_middleware(dp.fsm)
    dp.include_router(menu.router)
    dp.include_router(context_router)
    dp.include_router(copilot.router)
    dp.include_router(mentor.router)
    dp.include_router(workflow.router)
    dp.include_router(agent_flow.router)
    dp.include_router(history.router)   # <- тут
    dp.include_router(chat.router)
    dp.startup.register(register_commands)
    return dp


async def register_commands(bot):
    from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
    await bot.set_my_commands([
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="new", description="Новый запрос"),
        BotCommand(command="history", description="Проекты и история"),
        BotCommand(command="active", description="Текущий контекст"),
        BotCommand(command="case_history", description="Обсуждение стратегии"),
        BotCommand(command="cancel", description="Отменить уточнения"),
        BotCommand(command="help", description="Помощь"),
    ], scope=BotCommandScopeAllPrivateChats())


async def main():
    setup_logging()
    validate_configuration()
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = create_dispatcher()
    # Close the Telegram session only after the delivery owner has stopped.
    async with bot:
        async with asyncio.TaskGroup() as group:
            group.create_task(delivery_loop(bot, dp.delivery_stop))
            try:
                await dp.start_polling(bot, close_bot_session=False)
            except BaseException:
                # Unexpected polling failures retain the existing hard-cleanup
                # behavior and must never produce a successful drain marker.
                updates = tuple(dp._handle_update_tasks)
                for task in updates:
                    task.cancel()
                await asyncio.gather(*updates, return_exceptions=True)
                await dp["operation_guard"].close()
                raise
            finally:
                dp.delivery_stop.set()
    log.info("event=telegram_release_drained")


if __name__ == "__main__":
    asyncio.run(main())
