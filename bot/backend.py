"""Shared credentials and actor mapping for trusted backend requests."""
from app.config import settings


def actor_headers(telegram_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.BOT_BACKEND_TOKEN}",
        "X-Telegram-User-ID": str(telegram_id),
    }
