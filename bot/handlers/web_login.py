"""Private Telegram UI for browser session confirmation."""
import re

from aiogram import types

from app.config import settings
from bot import backend

LOGIN = "Открыть Brenvio"


def available():
    return settings.WEB_API_ENABLED and settings.WEB_TELEGRAM_LOGIN_ENABLED


def eligible(message):
    return (available() and message.chat.type == "private" and message.from_user
            and not message.from_user.is_bot and message.from_user.id == message.chat.id
            and not message.forward_origin and not message.sender_chat and not message.via_bot)


async def send_link(message: types.Message):
    if not eligible(message):
        return
    try:
        result = await backend.request("POST", "/internal/identity/web-login-link", message.from_user.id)
        url = result.get("url") if isinstance(result, dict) else None
        prefix = settings.WEB_APP_ORIGIN + "/auth/telegram#t="
        if not isinstance(url, str) or not re.fullmatch(re.escape(prefix) + r"[A-Za-z0-9_-]{43}", url):
            raise backend.BackendError("Invalid login link")
    except backend.BackendError:
        await message.answer("Ссылка сейчас недоступна. Попробуйте позже.")
        return
    await message.answer(url, parse_mode=None, disable_web_page_preview=True, protect_content=True)


async def confirm(message: types.Message):
    if not eligible(message):
        return
    args = (message.text or "").split()
    if len(args) != 2 or not re.fullmatch(r"[A-Za-z0-9_-]{22}", args[1]):
        await message.answer("Скопируйте команду подтверждения целиком из своего браузера.")
        return
    try:
        await backend.request("POST", "/internal/identity/web-login-confirm", message.from_user.id,
                              payload={"confirmation_code": args[1]})
    except backend.BackendError:
        await message.answer("Подтверждение не получено. Проверьте попытку в браузере или запросите новую ссылку.")
        return
    await message.answer("Вход подтверждён. Нажмите «Войти» в том же браузере.")
