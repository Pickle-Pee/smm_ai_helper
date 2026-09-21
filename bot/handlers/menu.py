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
        "Связный маркетинговый проект:\n"
        "/brand продукт | аудитория | цель — сохранить профиль бизнеса\n"
        "/analyze https://конкурент.ru — анализ → креативный пакет → объяснение по кнопке\n"
        "/runs — сохранённые проекты\n\n"
        "Просто напиши запрос одним сообщением. Например:\n"
        "• Сделай стратегию продвижения для приложения «Название»\n"
        "• Посмотри сайт https://example.com и предложи, что улучшить\n"
        "• Сгенерируй креатив для рекламного поста ВК\n"
        "\n/new — новый запрос\n"
        "/cancel — отменить уточнения до запуска анализа\n"
        "/copilot_status — проверить готовность последнего запроса\n"
        "/copilot_runs — найти сохранённые запросы и результаты после перезапуска\n"
    )

    await message.answer(text)
