"""Shared credentials and actor mapping for trusted backend requests."""
from app.config import settings
import asyncio
import re
import httpx

MAX_IMAGE_BYTES = 10 * 1024 * 1024


class BackendError(RuntimeError):
    pass


def validate_configuration():
    from aiogram.utils.token import validate_token, TokenValidationError
    try:
        url = httpx.URL(settings.API_BASE_URL)
        if (url.scheme not in ("http", "https") or not url.host or url.userinfo
                or url.query or url.fragment or not settings.BOT_BACKEND_TOKEN.strip()):
            raise ValueError()
        validate_token(settings.TELEGRAM_BOT_TOKEN)
    except (ValueError, TypeError, httpx.InvalidURL, TokenValidationError):
        raise ValueError("Bot requires a valid API_BASE_URL, BOT_BACKEND_TOKEN and TELEGRAM_BOT_TOKEN") from None


def actor_headers(telegram_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.BOT_BACKEND_TOKEN}",
        "X-Telegram-User-ID": str(telegram_id),
    }


async def request(method, path, actor_id, *, payload=None):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(method, settings.API_BASE_URL.rstrip("/") + path,
                                            headers=actor_headers(actor_id), json=payload)
    except httpx.HTTPError as exc:
        raise BackendError("Ответ сервера не получен. Запрос мог быть принят; проверьте /runs перед повтором."
            if method.upper() in {"POST", "PATCH", "PUT"}
            else "Сервер временно недоступен. Повторите просмотр позже.") from exc
    if response.status_code >= 400:
        messages = {
            401: "Не удалось подтвердить доступ к серверу. Обратитесь к администратору.",
            403: "Доступ к этому действию запрещён.",
            404: "Сохранённый результат не найден или недоступен.",
            409: "Действие конфликтует с текущим состоянием. Проверьте статус проекта.",
            429: "Слишком много запросов. Повторите команду позже.",
        }
        raise BackendError(messages.get(response.status_code,
            "Сервер временно недоступен. Проверьте статус проекта перед повтором."
            if response.status_code >= 500 else "Проверьте формат команды и повторите запрос."))
    try:
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError()
        return data
    except ValueError as exc:
        raise BackendError("Сервер вернул некорректный ответ. Проверьте статус проекта позже.") from exc


async def fetch_image(client, url: str, actor_id: int) -> bytes:
    """Fetch only owned backend image resources with bounded time and memory.

    All supported image producers return /images/{id}.png. Never forward the
    trusted service credentials to a model-supplied URL or a redirect target.
    """
    try:
        if not isinstance(url, str):
            raise ValueError()
        base = httpx.URL(settings.API_BASE_URL.rstrip("/"))
        target = httpx.URL(url)
        if target.is_relative_url:
            if target.host or not url.startswith("/images/"):
                raise ValueError()
            target = httpx.URL(str(base).rstrip("/") + url)
        if ((target.scheme, target.host, target.port) != (base.scheme, base.host, base.port)
                or target.userinfo or target.query or target.fragment
                or not re.fullmatch(re.escape(base.path.rstrip("/")) + r"/images/[A-Za-z0-9_-]+\.png", target.path)):
            raise ValueError()
        async with asyncio.timeout(30):
            async with client.stream("GET", target, headers=actor_headers(actor_id), follow_redirects=False) as response:
                if response.status_code != 200:
                    raise BackendError("Не удалось получить сохранённое изображение. Повторите просмотр позже.")
                length = response.headers.get("content-length")
                if length is not None and int(length) > MAX_IMAGE_BYTES:
                    raise ValueError()
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    if len(data) + len(chunk) > MAX_IMAGE_BYTES:
                        raise ValueError()
                    data.extend(chunk)
                if not data:
                    raise ValueError()
                return bytes(data)
    except (ValueError, TypeError, httpx.HTTPError, TimeoutError) as exc:
        raise BackendError("Не удалось загрузить изображение: недоступный адрес, файл или превышен размер.") from exc
