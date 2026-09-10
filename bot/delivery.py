"""Poll durable delivery claims. Telegram failures never invoke generation."""
import asyncio
import logging

import httpx
from aiogram import types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from app.config import settings
from bot.backend import actor_headers

log = logging.getLogger(__name__)


async def deliver_once(bot, client):
    base = settings.API_BASE_URL.rstrip("/")
    service_headers = {"Authorization": f"Bearer {settings.BOT_BACKEND_TOKEN}"}
    response = await client.post(base + "/internal/delivery/claim", headers=service_headers)
    response.raise_for_status()
    claim = response.json()
    if claim is None:
        return False
    actor, payload = claim["telegram_id"], claim["payload"]
    ack = {"claim_token": claim["claim_token"]}
    try:
        async with asyncio.timeout(60):
            if payload["kind"] == "image":
                image = await client.get(base + f"/images/{payload['image_id']}.png", headers=actor_headers(actor))
                image.raise_for_status()
                sent = await bot.send_photo(actor, types.BufferedInputFile(image.content, filename="creative.png"), request_timeout=30)
            else:
                markup = payload.get("reply_markup")
                sent = await bot.send_message(actor, payload["text"], parse_mode=None,
                    reply_markup=types.InlineKeyboardMarkup.model_validate(markup) if markup else None,
                    request_timeout=30)
            ack["message_id"] = sent.message_id
    except TelegramRetryAfter as exc:
        ack.update(retryable=True, retry_after=min(3600, exc.retry_after))
    except (TelegramForbiddenError, TelegramBadRequest):
        ack["retryable"] = False
    except Exception as exc:
        log.warning("Delivery failed delivery_id=%s error_type=%s", claim["delivery_id"], type(exc).__name__)
        ack["retryable"] = True
    # A failed/ambiguous acknowledgement leaves a reclaimable lease. No generation.
    result = await client.post(base + f"/internal/delivery/{claim['delivery_id']}/ack", json=ack, headers=service_headers)
    result.raise_for_status()
    return True


async def delivery_loop(bot):
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            try:
                if not await deliver_once(bot, client):
                    await asyncio.sleep(1)
            except Exception as exc:
                log.warning("Delivery backend unavailable error_type=%s", type(exc).__name__)
                await asyncio.sleep(2)
