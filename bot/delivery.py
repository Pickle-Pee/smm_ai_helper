"""Poll durable delivery claims. Telegram failures never invoke generation."""
import asyncio
import logging

import httpx
from aiogram import types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from app.config import settings
from bot import copilot_contracts as dto
from bot.backend import actor_headers, fetch_image, service_headers
from bot.copilot_client import RUN_ID
from bot.copilot_flow import run_messages

log = logging.getLogger(__name__)


class _PermanentDeliveryError(Exception):
    """The notice cannot be rendered for this owner; retrying cannot help."""


class _RunNotReady(Exception):
    """The run is not terminal yet; a notice is only created at terminal state."""


async def _run_messages(client, base, actor, payload):
    # Read-only owner-scoped projection of persisted artifacts: no execution, no provider.
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise _PermanentDeliveryError()
    response = await client.get(base + f"/copilot/runs/{run_id}", headers=actor_headers(actor), timeout=30)
    if response.status_code == 404:
        raise _PermanentDeliveryError()
    response.raise_for_status()
    run = dto.RunResponse.model_validate_json(response.content)
    if run.run_id != run_id:
        raise _PermanentDeliveryError()
    if run.status in {dto.RunStatus.QUEUED, dto.RunStatus.RUNNING}:
        raise _RunNotReady()
    title = payload.get("title")
    return run_messages(run, title=title if isinstance(title, str) else None)


async def _send_run(bot, client, base, actor, payload, ack):
    messages = await _run_messages(client, base, actor, payload)
    start = payload.get("sent_parts", 0)
    if type(start) is not int or not 0 <= start <= len(messages):
        start = 0
    ack["sent_parts"] = start
    sent = None
    for text, markup in messages[start:]:
        sent = await bot.send_message(actor, text, parse_mode=None, reply_markup=markup, request_timeout=30)
        # Confirmed by Telegram; a retry resumes after this message. An ambiguous
        # failure of the next send may still repeat that one message (at-least-once).
        ack["sent_parts"] += 1
    return sent


async def deliver_once(bot, client):
    base = settings.API_BASE_URL.rstrip("/")
    headers = service_headers()
    response = await client.post(base + "/internal/delivery/claim", headers=headers)
    response.raise_for_status()
    claim = response.json()
    if claim is None:
        return False
    actor, payload = claim["telegram_id"], claim["payload"]
    ack = {"claim_token": claim["claim_token"]}
    try:
        async with asyncio.timeout(60):
            if payload["kind"] == "image":
                image = await fetch_image(client, f"/images/{payload['image_id']}.png", actor)
                sent = await bot.send_photo(actor, types.BufferedInputFile(image, filename="creative.png"), request_timeout=30)
            elif payload["kind"] == "copilot_run":
                sent = await _send_run(bot, client, base, actor, payload, ack)
                if sent is None:
                    raise _PermanentDeliveryError()
            else:
                markup = payload.get("reply_markup")
                sent = await bot.send_message(actor, payload["text"], parse_mode=None,
                    reply_markup=types.InlineKeyboardMarkup.model_validate(markup) if markup else None,
                    request_timeout=30)
            ack["message_id"] = sent.message_id
            ack.pop("sent_parts", None)
    except TelegramRetryAfter as exc:
        ack.update(retryable=True, retry_after=min(3600, exc.retry_after))
    except (TelegramForbiddenError, TelegramBadRequest, _PermanentDeliveryError):
        ack["retryable"] = False
    except _RunNotReady:
        ack.update(retryable=True, retry_after=30)
    except Exception as exc:
        log.warning("Delivery failed delivery_id=%s error_type=%s", claim["delivery_id"], type(exc).__name__)
        ack["retryable"] = True
    # A failed/ambiguous acknowledgement leaves a reclaimable lease. No generation.
    result = await client.post(base + f"/internal/delivery/{claim['delivery_id']}/ack", json=ack, headers=headers)
    result.raise_for_status()
    return True


async def delivery_loop(bot, stop: asyncio.Event):
    async with httpx.AsyncClient(timeout=15) as client:
        while not stop.is_set():
            delay = 1
            try:
                if await deliver_once(bot, client):
                    continue
            except Exception as exc:
                log.warning("Delivery backend unavailable error_type=%s", type(exc).__name__)
                delay = 2
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except TimeoutError:
                pass
