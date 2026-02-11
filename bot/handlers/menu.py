# bot/handlers/menu.py
from __future__ import annotations

from aiogram import Router, types
from aiogram.filters import CommandStart
from html import escape

router = Router()


@router.message(CommandStart())
async def start(message: types.Message):
    text = (
        "Привет! Я помогу с продвижением: стратегия, контент, реклама, аудит.\n\n"
        "Просто напиши запрос одним сообщением. Например:\n"
        "• Сделай стратегию продвижения для приложения «Название»\n"
        "• Посмотри сайт https://example.com и предложи, что улучшить\n"
        "• Сгенерируй креатив для рекламного поста ВК\n"
    )

    await message.answer(text)
