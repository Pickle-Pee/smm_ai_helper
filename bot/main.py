# bot/main.py
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode

from app.config import settings
from bot.handlers import menu, agent_flow, history


async def main():
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    dp.include_router(menu.router)
    dp.include_router(agent_flow.router)
    dp.include_router(history.router)   # <- тут
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
