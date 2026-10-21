# bot/main.py
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation
from app.config import settings
from app.logging import setup_logging
from bot.backend import validate_configuration
from bot.handlers import menu, agent_flow, history, chat, workflow, copilot, mentor
from bot.delivery import delivery_loop
from bot.operation_guard import OperationGuard


def create_dispatcher():
    # Serialize a user's message/callback FSM updates, including HTTP awaits.
    dp = Dispatcher(events_isolation=SimpleEventIsolation(), disable_fsm=True)
    guard = OperationGuard()
    dp["operation_guard"] = guard
    dp.update.outer_middleware(guard)
    dp.update.outer_middleware(dp.fsm)
    dp.include_router(menu.router)
    dp.include_router(copilot.router)
    dp.include_router(mentor.router)
    dp.include_router(workflow.router)
    dp.include_router(agent_flow.router)
    dp.include_router(history.router)   # <- тут
    dp.include_router(chat.router)
    return dp


async def main():
    setup_logging()
    validate_configuration()
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = create_dispatcher()
    # Close the Telegram session only after the delivery owner has stopped.
    async with bot:
        async with asyncio.TaskGroup() as group:
            delivery_task = group.create_task(delivery_loop(bot))
            try:
                await dp.start_polling(bot, close_bot_session=False)
            finally:
                delivery_task.cancel()
                # Aiogram owns tasks before they enter our middleware (including
                # tasks waiting for its concurrency semaphore). start_polling
                # does not drain this set when polling stops.
                updates = tuple(dp._handle_update_tasks)
                for task in updates:
                    task.cancel()
                await asyncio.gather(*updates, return_exceptions=True)
                await dp["operation_guard"].close()


if __name__ == "__main__":
    asyncio.run(main())
