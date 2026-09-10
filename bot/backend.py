"""Shared credentials and actor mapping for trusted backend requests."""
from app.config import settings
import httpx


class BackendError(RuntimeError):
    pass


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
        raise BackendError("Сервер временно недоступен. Повторите команду позже.") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        raise BackendError(detail if isinstance(detail, str) else "Проверьте формат команды и повторите запрос.")
    return response.json()
