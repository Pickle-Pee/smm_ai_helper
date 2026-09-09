# bot/main.py
import asyncio

from aiogram import Bot, Dispatcher
from app.config import settings
from bot.handlers import menu, agent_flow, history, chat, workflow
from bot.delivery import delivery_loop


async def main():
    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN
    )
    dp = Dispatcher()
    dp.include_router(menu.router)
    dp.include_router(workflow.router)
    dp.include_router(agent_flow.router)
    dp.include_router(history.router)   # <- тут
    dp.include_router(chat.router)
    async with asyncio.TaskGroup() as group:
        delivery_task = group.create_task(delivery_loop(bot))
        try:
            await dp.start_polling(bot)
        finally:
            delivery_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
