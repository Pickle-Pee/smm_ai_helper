# bot/handlers/history.py
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import httpx

from app.config import settings
from bot.backend import actor_headers

router = Router()


def agent_human_name(agent_type: str) -> str:
    mapping = {
        "strategy": "Стратегия",
        "content": "Контент",
        "analytics": "Аналитика",
        "promo": "Продвижение",
        "trends": "Тренды",
    }
    return mapping.get(agent_type, agent_type)


def history_item_kb(task_id: int, agent_type: str) -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text="Показать результат",
        callback_data=f"task_show:{task_id}",
    )
    kb.button(
        text="Повторить задачу",
        callback_data=f"task_repeat:{task_id}:{agent_type}",
    )
    kb.adjust(2)
    return kb.as_markup()


@router.message(Command("history"))
async def cmd_history(message: types.Message):
    """
    Показываем последние N задач пользователя (по его Telegram ID).
    """
    user_id = message.from_user.id

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{settings.API_BASE_URL}/tasks/by_user/{user_id}",
            params={"limit": 10},
            headers=actor_headers(user_id),
        )
        if resp.status_code >= 400:
            await message.answer("Не удалось получить историю задач 😔")
            return
        tasks = resp.json()

    if not tasks:
        await message.answer("История пока пустая. Сначала запусти одного из агентов 🙂")
        return

    for t in tasks:
        task_id = t["id"]
        agent_type = t["agent_type"]
        created_at = t["created_at"]
        desc = t["task_description"]
        short_desc = desc if len(desc) <= 120 else desc[:117] + "..."

        text = (
            f"<b>#{task_id}</b> · {agent_human_name(agent_type)}\n"
            f"{created_at}\n\n"
            f"{short_desc}"
        )
        await message.answer(
            text,
            reply_markup=history_item_kb(task_id, agent_type),
        )


async def fetch_task(task_id: int, actor_id: int) -> dict | None:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(f"{settings.API_BASE_URL}/tasks/{task_id}", headers=actor_headers(actor_id))
        if resp.status_code >= 400:
            return None
        return resp.json()


@router.callback_query(F.data.startswith("task_show:"))
async def on_task_show(callback: types.CallbackQuery):
    """
    Показать результат уже выполненной задачи (без перезапуска агента).
    Используем тот же формат, что и при первом ответе:
    - для стратегии выводим краткий дайджест,
    - для остальных менеджерим по типу агента.
    """
    from .agent_flow import (  # локальный импорт, чтобы избежать циклов
        format_strategy_result,
        format_content_result_digest,
        format_analytics_digest,
        format_promo_digest,
        format_trends_digest,
    )

    _, task_id_str = callback.data.split(":", 1)
    task_id = int(task_id_str)

    task = await fetch_task(task_id, callback.from_user.id)
    if not task:
        await callback.answer("Не удалось получить задачу 😔", show_alert=True)
        return

    agent_type = task["agent_type"]
    result = task.get("result") or {}

    # лёгкое ветвление по типу агента
    if agent_type == "strategy":
        text = format_strategy_result(result)
        await callback.message.answer(text[:4000])
    elif agent_type == "content":
        msgs = format_content_result_digest(result)
        for txt in msgs:
            await callback.message.answer(txt[:4000])
    elif agent_type == "analytics":
        msgs = format_analytics_digest(result)
        for txt in msgs:
            await callback.message.answer(txt[:4000])
    elif agent_type == "promo":
        msgs = format_promo_digest(result)
        for txt in msgs:
            await callback.message.answer(txt[:4000])
    elif agent_type == "trends":
        msgs = format_trends_digest(result)
        for txt in msgs:
            await callback.message.answer(txt[:4000])
    else:
        await callback.message.answer("Тип агента для этой задачи пока не поддержан в просмотре.")

    await callback.answer()


@router.callback_query(F.data.startswith("task_repeat:"))
async def on_task_repeat(callback: types.CallbackQuery):
    """
    Повтор задачи: вытаскиваем старый brief (task_description + answers)
    и запускаем соответствующего агента ещё раз.
    """
    _, rest = callback.data.split(":", 1)
    task_id_str, agent_type = rest.split(":", 1)
    task_id = int(task_id_str)

    task = await fetch_task(task_id, callback.from_user.id)
    if not task:
        await callback.answer("Не удалось получить задачу для повтора 😔", show_alert=True)
        return

    task_description = task["task_description"]
    answers = task.get("answers") or {}

    await callback.message.answer("Повторяю задачу с теми же вводными… 🤖")

    payload = {
        "user": {
            "telegram_id": callback.from_user.id,
            "username": callback.from_user.username,
            "first_name": callback.from_user.first_name,
            "last_name": callback.from_user.last_name,
        },
        "agent_type": agent_type,
        "task_description": task_description,
        "answers": answers,
    }

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{settings.API_BASE_URL}/agents/{agent_type}/run",
            json=payload,
            headers=actor_headers(callback.from_user.id),
        )
        if resp.status_code >= 400:
            await callback.message.answer(
                "Произошла ошибка при повторном запуске задачи 😔"
            )
            await callback.answer()
            return
        data_resp = resp.json()

    new_task_id = data_resp["task_id"]
    result = data_resp["result"]

    # импортируем форматтеры
    from .agent_flow import (
        format_strategy_result,
        format_content_result_digest,
        format_analytics_digest,
        format_promo_digest,
        format_trends_digest,
        kb_strategy_more,
        kb_content_more,
        kb_analytics_more,
        kb_promo_more,
        kb_trends_more,
    )

    # показываем результат аналогично первому запуску
    if agent_type == "strategy":
        text = format_strategy_result(result)
        await callback.message.answer(
            text[:4000],
            reply_markup=kb_strategy_more(new_task_id),
        )

    elif agent_type == "content":
        msgs = format_content_result_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await callback.message.answer(
                    txt[:4000],
                    reply_markup=kb_content_more(new_task_id),
                )
            else:
                await callback.message.answer(txt[:4000])

    elif agent_type == "analytics":
        msgs = format_analytics_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await callback.message.answer(
                    txt[:4000],
                    reply_markup=kb_analytics_more(new_task_id),
                )
            else:
                await callback.message.answer(txt[:4000])

    elif agent_type == "promo":
        msgs = format_promo_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await callback.message.answer(
                    txt[:4000],
                    reply_markup=kb_promo_more(new_task_id),
                )
            else:
                await callback.message.answer(txt[:4000])

    elif agent_type == "trends":
        msgs = format_trends_digest(result)
        for i, txt in enumerate(msgs):
            if i == len(msgs) - 1:
                await callback.message.answer(
                    txt[:4000],
                    reply_markup=kb_trends_more(new_task_id),
                )
            else:
                await callback.message.answer(txt[:4000])
    else:
        await callback.message.answer("Повтор задачи выполнен, но формат ответа пока не настроен.")

    await callback.answer()
