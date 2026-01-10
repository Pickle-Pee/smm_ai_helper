# bot/handlers/chat.py
from __future__ import annotations

import hashlib
from typing import Dict, List

import httpx
from aiogram import F, Router, types
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings


router = Router()
ACTION_STORE: Dict[str, Dict[str, str]] = {}


def _make_action_key(user_id: int, text: str) -> str:
    digest = hashlib.sha256(f"{user_id}:{text}".encode("utf-8")).hexdigest()[:12]
    return digest


def _actions_keyboard(user_id: int, actions: List[Dict[str, str]]):
    kb = InlineKeyboardBuilder()
    store = ACTION_STORE.setdefault(str(user_id), {})
    store.clear()
    for action in actions:
        text = action.get("text", "").strip()
        if not text:
            continue
        key = _make_action_key(user_id, text)
        store[key] = text
        kb.button(text=text[:30], callback_data=f"action:{key}")
    kb.adjust(1)
    return kb.as_markup() if store else None


async def _send_to_backend(message: types.Message, text: str) -> None:
    payload = {"user_id": f"tg:{message.from_user.id}", "text": text, "attachments": []}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(f"{settings.API_BASE_URL}/chat/message", json=payload)
    if resp.status_code >= 400:
        await message.answer("Не получилось обработать сообщение. Попробуй ещё раз.")
        return
    data = resp.json()
    reply = data.get("reply") or "Готово."
    follow_up = data.get("follow_up_question")
    actions = data.get("actions") or []

    kb = _actions_keyboard(message.from_user.id, actions)
    await message.answer(reply[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    if follow_up:
        await message.answer(follow_up[:1000])


@router.message(F.text & ~F.text.startswith("/"))
async def chat_message(message: types.Message):
    await _send_to_backend(message, message.text)


@router.callback_query(F.data.startswith("action:"))
async def on_action(callback: types.CallbackQuery):
    key = callback.data.split(":", 1)[1]
    store = ACTION_STORE.get(str(callback.from_user.id), {})
    text = store.get(key)
    if not text:
        await callback.answer("Действие устарело", show_alert=True)
        return
    await callback.message.answer("Ок, делаю...")
    await _send_to_backend(callback.message, text)
    await callback.answer()
