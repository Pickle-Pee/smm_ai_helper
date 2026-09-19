# bot/main.py
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation
from app.config import settings
from bot.handlers import menu, agent_flow, history, chat, workflow, copilot
from bot.delivery import delivery_loop


def create_dispatcher():
    # Serialize a user's message/callback FSM updates, including HTTP awaits.
    dp = Dispatcher(events_isolation=SimpleEventIsolation())
    dp.include_router(menu.router)
    dp.include_router(copilot.router)
    dp.include_router(workflow.router)
    dp.include_router(agent_flow.router)
    dp.include_router(history.router)   # <- тут
    dp.include_router(chat.router)
    return dp


async def main():
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = create_dispatcher()
    async with asyncio.TaskGroup() as group:
        delivery_task = group.create_task(delivery_loop(bot))
        try:
            await dp.start_polling(bot)
        finally:
            delivery_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
