# bot/handlers/chat.py
from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import httpx
from aiogram import F, Router, types
from aiogram.enums import ChatAction, ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings


router = Router()
ACTION_STORE: Dict[str, Dict[str, str]] = {}


def _make_action_key(user_id: int, text: str) -> str:
    digest = hashlib.sha256(f"{user_id}:{text}".encode("utf-8")).hexdigest()[:12]
    return digest


def _actions_keyboard(user_id: int, actions: Any):
    kb = InlineKeyboardBuilder()
    store = ACTION_STORE.setdefault(str(user_id), {})
    store.clear()

    if not actions or not isinstance(actions, list):
        return None

    for action in actions:
        if not isinstance(action, dict):
            continue
        text = (action.get("text") or "").strip()
        if not text:
            continue
        key = _make_action_key(user_id, text)
        store[key] = text
        kb.button(text=text[:30], callback_data=f"action:{key}")

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


def _abs_url(url: str) -> str:
    # url может быть относительный: /images/{id}.png
    base = (settings.API_BASE_URL or "").rstrip("/")
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not url.startswith("/"):
        url = "/" + url
    return f"{base}{url}"


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


async def _send_images_from_response(message: types.Message, data: Dict[str, Any]) -> None:
    """
    Вытаскивает ссылки на картинки из ответа бэка и отправляет до 3 изображений.
    """
    images = _extract_images_anywhere(data)
    if not images:
        return

    async with httpx.AsyncClient(timeout=60) as client:
        for img in images[:3]:
            url = img.get("url")
            if not url:
                continue
            full_url = _abs_url(url)
            try:
                r = await client.get(full_url)
                if r.status_code >= 400:
                    continue
                bio = BytesIO(r.content)
                await message.answer_photo(
                    types.BufferedInputFile(bio.getvalue(), filename="image.png")
                )
            except Exception:
                # не валим весь ответ из-за одного изображения
                continue


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


async def _send_to_backend(message: types.Message, text: str) -> None:
    wants_image = _wants_image(text)
    prepared_text = _augment_text_for_image_request(text) if wants_image else text

    payload = {
        "user_id": f"tg:{message.from_user.id}",
        "text": prepared_text,
        "attachments": [],
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
            )

        if resp.status_code >= 400:
            try:
                await status_msg.edit_text("Не получилось обработать сообщение. Попробуй ещё раз.")
            except Exception:
                await message.answer("Не получилось обработать сообщение. Попробуй ещё раз.")
            return

        data: Dict[str, Any] = resp.json()

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
            await _send_images_from_response(message, data)
        except Exception:
            await message.answer(
                "Картинку не удалось отправить, но генерация могла сохраниться на сервере."
            )

        # 3) текст + actions
        if not reply:
            reply = "Готово."

        kb = _actions_keyboard(message.from_user.id, actions)
        try:
            await message.answer(reply[:4000], parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        except Exception:
            # если markdown “сломался” — отправим без него
            await message.answer(reply[:4000], parse_mode=None, reply_markup=kb)

        # 4) follow-up
        if isinstance(follow_up, str) and follow_up.strip():
            await message.answer(follow_up.strip()[:1000])

        # 5) можно удалить статус “✅ Готово.”, чтобы не засорять чат
        # (если хочешь оставить — просто закомментируй)
        try:
            await status_msg.delete()
        except Exception:
            pass

    finally:
        action_task.cancel()
        long_task.cancel()


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

    # более UX-но: не спамим “Ок, делаю...” в чат, а показываем toast
    await callback.answer("Ок, выполняю…")
    await _send_to_backend(callback.message, text)
