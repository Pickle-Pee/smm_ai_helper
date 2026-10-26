# bot/handlers/chat.py
from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from aiogram import F, Router, types
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings
from bot.backend import actor_headers, fetch_image, BackendError
from bot.rendering import send_text
from bot.copilot_flow import CopilotStates, receive


router = Router()
ACTION_STORE: Dict[str, Dict[str, str]] = {}
ACTION_LABEL_MAX_CHARS = 30
ACTION_MAX_USERS = 1000
ACTION_MAX_PER_USER = 10
ACTION_MAX_TEXT_CHARS = 4000
ACTION_TTL_SECONDS = 15 * 60
# Separate metadata keeps the existing actor -> token -> text interface intact.
ACTION_EXPIRES: Dict[str, float] = {}


def _prune_actions():
    """Expire at creation/consumption; oldest keyboards are evicted at capacity.

    Expiry never slides on access. A new keyboard invalidates that actor's old
    tokens. Restart, expiry and eviction all fail closed; no durable recovery.
    """
    now = time.monotonic()
    for actor in list(ACTION_EXPIRES):
        if actor not in ACTION_STORE:
            ACTION_EXPIRES.pop(actor, None)
    for actor in list(ACTION_STORE):
        if ACTION_EXPIRES.get(actor, 0) <= now:
            ACTION_STORE.pop(actor, None)
            ACTION_EXPIRES.pop(actor, None)


def _short_action_label(text: str, limit: int = ACTION_LABEL_MAX_CHARS) -> str:
    """Fit a display label while preserving complete words where possible."""
    if limit < 0:
        raise ValueError("Action label limit must be non-negative")
    if limit == 0:
        return ""

    text = " ".join(text.split())
    if len(text) <= limit:
        return text

    prefix_length = limit - 1
    boundary = text.rfind(" ", 0, prefix_length + 1)
    prefix = text[:boundary] if boundary > 0 else text[:prefix_length]
    return prefix.rstrip(" ,.;:!?") + "…"


def _make_action_key(user_id: int, text: str) -> str:
    digest = hashlib.sha256(f"{user_id}:{secrets.token_hex(16)}:{text}".encode("utf-8")).hexdigest()[:32]
    return digest


def _actions_keyboard(user_id: int, actions: Any):
    kb = InlineKeyboardBuilder()
    _prune_actions()
    actor = str(user_id)
    ACTION_STORE.pop(actor, None)
    ACTION_EXPIRES.pop(actor, None)
    store = {}

    if not actions or not isinstance(actions, list):
        return None

    for action in actions:
        if not isinstance(action, dict):
            continue
        value = action.get("text")
        text = value.strip() if isinstance(value, str) else ""
        if not text:
            continue
        if len(text) > ACTION_MAX_TEXT_CHARS:
            continue
        key = _make_action_key(user_id, text)
        store[key] = text
        kb.button(text=_short_action_label(text), callback_data=f"action:{key}")
        if len(store) == ACTION_MAX_PER_USER:
            break

    if store:
        while len(ACTION_STORE) >= ACTION_MAX_USERS:
            oldest = next(iter(ACTION_STORE))
            ACTION_STORE.pop(oldest)
            ACTION_EXPIRES.pop(oldest, None)
        ACTION_STORE[actor] = store
        ACTION_EXPIRES[actor] = time.monotonic() + ACTION_TTL_SECONDS

    kb.adjust(1)
    return kb.as_markup() if store else None


def _infer_style_and_variants(text: str) -> Tuple[Optional[str], int]:
    """
    Простая эвристика:
    - стиль: minimal / bright / premium
    - variants: "3 варианта", "2 версии" и т.п.
    """
    t = (text or "").lower()

    style: Optional[str] = None
    if any(k in t for k in ["минимал", "минималист", "minimal"]):
        style = "minimal"
    elif any(k in t for k in ["ярк", "игров", "весёл", "fun", "playful"]):
        style = "bright"
    elif any(k in t for k in ["премиум", "люкс", "дорог", "premium", "lux"]):
        style = "premium"

    variants = 1
    if any(
        k in t
        for k in [
            "3 варианта",
            "три варианта",
            "3 версии",
            "три версии",
            "3 креатива",
            "три креатива",
        ]
    ):
        variants = 3
    elif any(
        k in t
        for k in [
            "2 варианта",
            "два варианта",
            "2 версии",
            "две версии",
            "2 креатива",
            "два креатива",
        ]
    ):
        variants = 2

    variants = max(1, min(variants, 3))
    return style, variants


def _augment_text_for_image_request(original_text: str) -> str:
    """
    Добавляем в текст подсказки, чтобы бэкенд мог выбрать variants/style,
    даже если он пока не парсит эти поля напрямую.
    """
    style, variants = _infer_style_and_variants(original_text)
    hints: List[str] = []
    if style:
        hints.append(f"style={style}")
    if variants and variants != 1:
        hints.append(f"variants={variants}")

    if not hints:
        return original_text

    return f"{original_text}\n\n[image_hints: {', '.join(hints)}]"


def _wants_image(text: str) -> bool:
    t = (text or "").lower()
    triggers = [
        "сгенерируй",
        "сделай картинку",
        "картин",
        "баннер",
        "креатив",
        "обложк",
        "визуал",
        "изображен",
        "постер",
        "poster",
        "image",
        "pic",
        "пикчу",
        "нарисуй",
    ]
    return any(k in t for k in triggers)


def _extract_images_anywhere(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Поддерживаем несколько вариантов структуры ответа.
    Ожидаем список объектов вида {"url": "..."}.
    """

    def _norm_images(x: Any) -> List[Dict[str, str]]:
        if not isinstance(x, list):
            return []
        out: List[Dict[str, str]] = []
        for item in x:
            if isinstance(item, dict) and item.get("url"):
                out.append({"url": str(item["url"])})
            elif isinstance(item, str) and item.strip():
                out.append({"url": item.strip()})
        return out

    # 1) data["images"]
    imgs = _norm_images(data.get("images"))
    if imgs:
        return imgs

    # 2) data["image"]["images"]
    image_payload = data.get("image")
    if isinstance(image_payload, dict):
        imgs = _norm_images(image_payload.get("images"))
        if imgs:
            return imgs

    # 3) data["result"]["image"]["images"] или data["result"]["images"]
    result = data.get("result")
    if isinstance(result, dict):
        imgs = _norm_images(result.get("images"))
        if imgs:
            return imgs
        img2 = result.get("image")
        if isinstance(img2, dict):
            imgs = _norm_images(img2.get("images"))
            if imgs:
                return imgs

    return []


async def _send_images_from_response(message: types.Message, data: Dict[str, Any], *, actor_id: int) -> None:
    """
    Отправляет все сохранённые изображения через ограниченный backend media client.
    """
    images = _extract_images_anywhere(data)
    if not images:
        return

    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        for img in images:
            try:
                content = await fetch_image(client, img["url"], actor_id)
                await message.answer_photo(types.BufferedInputFile(content, filename="image.png"))
            except (BackendError, httpx.HTTPError, TelegramAPIError):
                await message.answer("Не удалось доставить изображение. Генерация не запускается повторно; проверьте сохранённый результат позже.")


async def _chat_action_indicator(message: types.Message, wants_image: bool) -> None:
    """
    Периодически отправляем chat action, пока идёт запрос.
    """
    action = ChatAction.UPLOAD_PHOTO if wants_image else ChatAction.TYPING
    try:
        while True:
            await message.bot.send_chat_action(chat_id=message.chat.id, action=action)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        return


async def _long_request_indicator(status_msg: types.Message) -> None:
    """
    Индикатор для длинных запросов:
    - через 12 сек обновляет статус
    - через 30 сек обновляет статус ещё раз
    """
    try:
        await asyncio.sleep(12)
        try:
            await status_msg.edit_text("⏳ Всё ещё выполняю… (может занять до минуты)")
        except Exception:
            pass

        await asyncio.sleep(18)  # итого 30 сек
        try:
            await status_msg.edit_text("⏳ Почти готово… ещё немного")
        except Exception:
            pass
    except asyncio.CancelledError:
        return


async def _send_to_backend(message: types.Message, text: str, *, actor_id: int, request_key: str | None = None) -> None:
    from bot.project_navigation import binding
    try:
        current = await binding(actor_id, message.chat.id)
    except (BackendError, ValueError, KeyError, TypeError):
        await send_text(message, "Не удалось проверить текущий контекст. Запрос не отправлен; откройте меню.")
        return
    if current.get("active") is not None:
        await send_text(message, "Выбран сохранённый проект. Напишите запрос в его диалоге или нажмите «Новый запрос».")
        return
    wants_image = _wants_image(text)
    prepared_text = _augment_text_for_image_request(text) if wants_image else text

    payload = {
        "user_id": f"tg:{actor_id}",
        "text": prepared_text,
        "attachments": [],
        "context_version": current["version"],
        "request_key": request_key or f"tg:{actor_id}:{message.chat.id}:{message.message_id}",
    }

    # 0) мгновенная индикация “в процессе”
    status_msg = await message.answer("⏳ Выполняю запрос…")

    # 1) фоновые индикаторы
    action_task = asyncio.create_task(_chat_action_indicator(message, wants_image))
    long_task = asyncio.create_task(_long_request_indicator(status_msg))

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{settings.API_BASE_URL.rstrip('/')}/chat/message",
                json=payload,
                headers=actor_headers(actor_id),
            )

        if resp.status_code >= 400:
            try:
                await status_msg.edit_text("Не получилось обработать сообщение. Попробуй ещё раз.")
            except Exception:
                await message.answer("Не получилось обработать сообщение. Попробуй ещё раз.")
            return

        data: Dict[str, Any] = resp.json()
        if not isinstance(data, dict) or not isinstance(data.get("reply", ""), str):
            raise ValueError("Invalid chat response")

        reply = (data.get("reply") or "").strip()
        follow_up = data.get("follow_up_question")
        actions = data.get("actions") or []

        # 2) картинки (если есть) — можно первыми, чтобы было “вау”
        # но сначала уберём статус, чтобы не было “⏳” + фотки без контекста
        try:
            await status_msg.edit_text("✅ Готово.")
        except Exception:
            pass

        try:
            await _send_images_from_response(message, data, actor_id=actor_id)
        except Exception:
            await message.answer(
                "Картинку не удалось отправить, но генерация могла сохраниться на сервере."
            )

        # 3) текст + actions
        if not reply:
            reply = "Готово."

        kb = _actions_keyboard(actor_id, actions)
        await send_text(message, reply, reply_markup=kb)

        # 4) follow-up
        if isinstance(follow_up, str) and follow_up.strip():
            await message.answer(follow_up.strip()[:1000], parse_mode=None)

        # 5) можно удалить статус “✅ Готово.”, чтобы не засорять чат
        # (если хочешь оставить — просто закомментируй)
        try:
            await status_msg.delete()
        except Exception:
            pass

    except (httpx.HTTPError, ValueError, TypeError):
        text = "Не удалось получить ответ сервера. Запрос мог быть обработан; повторная отправка может создать новый результат."
        try:
            await status_msg.edit_text(text)
        except TelegramAPIError:
            await message.answer(text)
    except asyncio.CancelledError:
        try:
            await status_msg.edit_text("Ожидание прервано. Запрос мог быть принят сервером.")
        except TelegramAPIError:
            pass
        raise
    finally:
        action_task.cancel()
        long_task.cancel()
        await asyncio.gather(action_task, long_task, return_exceptions=True)


@router.message(StateFilter(None, CopilotStates.pending), F.text & ~F.text.startswith("/"))
async def chat_message(message: types.Message, state: FSMContext):
    await receive(message, state)


@router.callback_query(F.data.startswith("action:"))
async def on_action(callback: types.CallbackQuery):
    if callback.message is None or callback.message.chat.type != "private":
        await callback.answer("Откройте личный чат с ботом.")
        return
    key = callback.data.split(":", 1)[1]
    _prune_actions()
    store = ACTION_STORE.get(str(callback.from_user.id), {})
    # Consume before the first await: concurrent deliveries cannot execute twice.
    text = store.pop(key, None)
    if not store:
        ACTION_STORE.pop(str(callback.from_user.id), None)
        ACTION_EXPIRES.pop(str(callback.from_user.id), None)

    if not text:
        await callback.answer("Действие устарело", show_alert=True)
        return

    # A keyboard generated by the old global chat must never bypass a selected
    # project's conversation boundary.
    from bot.project_navigation import binding
    try:
        current = await binding(callback.from_user.id, callback.message.chat.id)
    except (BackendError, ValueError, KeyError, TypeError):
        await callback.answer("Не удалось проверить текущий проект. Откройте меню.", show_alert=True)
        return
    if current.get("active") is not None:
        await callback.answer("Действие относится к старому чату. Напишите запрос в текущем проекте.", show_alert=True)
        return

    # более UX-но: не спамим “Ок, делаю...” в чат, а показываем toast
    await callback.answer("Ок, выполняю…")
    await _send_to_backend(callback.message, text, actor_id=callback.from_user.id,
        request_key=f"tg:{callback.from_user.id}:{callback.message.chat.id}:action:" + hashlib.sha256(callback.id.encode()).hexdigest()[:32])
