"""Owner-scoped saved task viewing and explicitly one-shot repeat buttons."""
import re
import secrets
from collections import OrderedDict

import httpx
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from bot.backend import actor_headers
from bot.rendering import send_text

router = Router()
AGENTS = {"strategy": "Стратегия", "content": "Контент", "analytics": "Аналитика", "promo": "Продвижение", "trends": "Тренды"}
# These buttons are local conveniences, deliberately expired by restart/new history.
# A repeat is a new synchronous generation, without durable backend acceptance.
REPEAT_BUTTONS = OrderedDict()


def agent_human_name(agent_type):
    return AGENTS.get(agent_type, agent_type)


def history_item_kb(task_id, agent_type, actor_id):
    token = secrets.token_hex(8)
    buttons = REPEAT_BUTTONS.setdefault(actor_id, {})
    REPEAT_BUTTONS.move_to_end(actor_id)
    while len(REPEAT_BUTTONS) > 1000:
        REPEAT_BUTTONS.popitem(last=False)
    buttons[token] = (task_id, agent_type)
    kb = InlineKeyboardBuilder()
    kb.button(text="Показать результат", callback_data=f"task_show:{task_id}")
    kb.button(text="Повторить задачу", callback_data=f"task_repeat:{task_id}:{agent_type}:{token}")
    kb.adjust(2)
    return kb.as_markup()


async def private_callback(callback):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer("Откройте личный чат с ботом.")
        return False
    return True


def task_id_from_callback(data):
    match = re.fullmatch(r"[a-z_]+:([1-9][0-9]{0,18})", data or "")
    return int(match[1]) if match else None


@router.message(Command("history"))
async def cmd_history(message):
    if message.chat.type != "private":
        await message.answer("Откройте личный чат с ботом.")
        return
    user_id = message.from_user.id
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{settings.API_BASE_URL}/tasks/by_user/{user_id}",
                                    params={"limit": 10}, headers=actor_headers(user_id))
            resp.raise_for_status()
            tasks = resp.json()
        if not isinstance(tasks, list) or any(not isinstance(t, dict) or
                not {"id", "agent_type", "created_at", "task_description"} <= t.keys()
                or type(t["id"]) is not int or not 0 < t["id"] <= 2**63 - 1
                or not isinstance(t["agent_type"], str) or t["agent_type"] not in AGENTS
                or not isinstance(t["created_at"], str) or not isinstance(t["task_description"], str) for t in tasks):
            raise ValueError()
    except (httpx.HTTPError, ValueError, TypeError):
        await message.answer("Не удалось получить историю задач. Повторите /history позже.")
        return
    REPEAT_BUTTONS.pop(user_id, None)
    if not tasks:
        await message.answer("История пока пустая. Сначала запустите одного из агентов.")
        return
    for task in tasks:
        desc = str(task["task_description"])
        text = f"#{task['id']} · {agent_human_name(task['agent_type'])}\n{task['created_at']}\n\n{desc[:120]}"
        await send_text(message, text, reply_markup=history_item_kb(task["id"], task["agent_type"], user_id))


async def fetch_task(task_id, actor_id):
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(f"{settings.API_BASE_URL}/tasks/{task_id}", headers=actor_headers(actor_id))
            resp.raise_for_status()
            task = resp.json()
        if (not isinstance(task, dict) or task.get("id") != task_id or task.get("agent_type") not in AGENTS
                or not isinstance(task.get("task_description"), str)
                or not isinstance(task.get("result"), (dict, type(None)))):
            return None
        return task
    except (httpx.HTTPError, ValueError, TypeError):
        return None


async def show_task(message, task, *, with_more=False):
    from . import agent_flow as agent
    agent_type = task["agent_type"]
    if task.get("status") != "done":
        await send_text(message, "Задача не завершена успешно. Результат пока недоступен.")
        return
    formatter = getattr(agent, {"strategy": "format_strategy_result", "content": "format_content_result_digest", "analytics": "format_analytics_digest", "promo": "format_promo_digest", "trends": "format_trends_digest"}[agent_type])
    output = agent.saved_output(formatter, task.get("result") or {})
    if output is None:
        await send_text(message, "Не удалось прочитать сохранённый результат. Обратитесь в поддержку.")
        return
    parts = [output] if isinstance(output, str) else output
    markup = getattr(agent, f"kb_{agent_type}_more")(task["id"]) if with_more else None
    for index, text in enumerate(parts):
        await send_text(message, text, reply_markup=markup if index == len(parts) - 1 else None)


@router.callback_query(F.data.startswith("task_show:"))
async def on_task_show(callback):
    if not await private_callback(callback):
        return
    task_id = task_id_from_callback(callback.data)
    if task_id is None:
        await callback.answer("Некорректное действие. Откройте /history", show_alert=True)
        return
    await callback.answer()
    task = await fetch_task(task_id, callback.from_user.id)
    if not task:
        await send_text(callback.message, "Не удалось получить задачу. Откройте /history позже.")
        return
    await show_task(callback.message, task)


@router.callback_query(F.data.startswith("task_repeat:"))
async def on_task_repeat(callback):
    if not await private_callback(callback):
        return
    match = re.fullmatch(r"task_repeat:([1-9][0-9]{0,18}):(strategy|content|analytics|promo|trends):([0-9a-f]{16})", callback.data or "")
    if not match:
        await callback.answer("Действие устарело. Откройте /history", show_alert=True)
        return
    task_id, agent_type, token = int(match[1]), match[2], match[3]
    # Atomic local consumption before await, also independent of dispatcher locks.
    stored = REPEAT_BUTTONS.get(callback.from_user.id, {}).pop(token, None)
    if stored != (task_id, agent_type):
        await callback.answer("Действие устарело. Для нового повтора откройте /history", show_alert=True)
        return
    await callback.answer("Проверяю сохранённую задачу…")
    task = await fetch_task(task_id, callback.from_user.id)
    if not task or task["agent_type"] != agent_type:
        await send_text(callback.message, "Не удалось получить задачу для повтора. Откройте /history.")
        return
    payload = {"user": {"telegram_id": callback.from_user.id, "username": callback.from_user.username,
                       "first_name": callback.from_user.first_name, "last_name": callback.from_user.last_name},
               "agent_type": task["agent_type"], "task_description": task["task_description"], "answers": task.get("answers") or {}}
    await send_text(callback.message, "Повторяю задачу с теми же вводными…")
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f"{settings.API_BASE_URL}/agents/{agent_type}/run", json=payload,
                                     headers=actor_headers(callback.from_user.id))
            resp.raise_for_status()
            result = resp.json()
        if not isinstance(result, dict) or not isinstance(result.get("task_id"), int) or not isinstance(result.get("result"), dict) or result.get("status") != "done":
            raise ValueError()
    except (httpx.HTTPError, ValueError, TypeError):
        await send_text(callback.message, "Не удалось подтвердить результат повтора. Он мог сохраниться: проверьте /history перед новым запуском.")
        return
    await show_task(callback.message, {"id": result["task_id"], "agent_type": agent_type,
                                     "status": result["status"], "result": result["result"]}, with_more=True)
