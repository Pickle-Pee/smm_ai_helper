# app/llm/openai_images.py
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Dict, Optional

import httpx

from app.config import settings

log = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _is_gpt_image_model(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith("gpt-image-")


def _is_verification_error(resp_text: str) -> bool:
    t = (resp_text or "").lower()
    return "must be verified" in t and "verify organization" in t


async def _download_image(url: str, timeout: httpx.Timeout) -> bytes:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def generate_image(
    prompt: str,
    size: str,
    model: str,
    quality: str = "auto",
    *,
    user: Optional[str] = None,
) -> bytes:
    """
    Возвращает PNG/JPEG/WEBP как bytes.
    - Для gpt-image-* API всегда возвращает b64_json (response_format не передаем).
    - Для dall-e-3 / dall-e-2 можно просить b64_json.
    """
    url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/images/generations"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}

    timeout = httpx.Timeout(settings.HTTP_TIMEOUT)

    async def _call(model_to_use: str) -> bytes:
        payload: Dict[str, Any] = {
            "model": model_to_use,
            "prompt": prompt,
            "size": size,
        }
        if user:
            payload["user"] = user

        if _is_gpt_image_model(model_to_use):
            # GPT image models:
            # - response_format НЕ поддерживается
            # - quality: low|medium|high|auto
            payload["quality"] = quality if quality in {"low", "medium", "high", "auto"} else "auto"
            # output_format можно задать, но по умолчанию png — ок
            # payload["output_format"] = "png"
        else:
            # dall-e-3 / dall-e-2:
            # - response_format поддерживается (url|b64_json)
            payload["response_format"] = "b64_json"
            # quality: standard|hd (dall-e-3), standard (dall-e-2)
            if model_to_use == "dall-e-3":
                payload["quality"] = "standard" if quality not in {"hd"} else "hd"
            else:
                payload["quality"] = "standard"

        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(settings.HTTP_RETRIES + 1):
                try:
                    resp = await client.post(url, headers=headers, json=payload)

                    if resp.status_code >= 400:
                        body = resp.text
                        log.error("OpenAI images error status=%s body=%s", resp.status_code, body[:4000])

                        # Не ретраим большинство 4xx
                        if resp.status_code not in RETRYABLE_STATUS_CODES:
                            resp.raise_for_status()

                    resp.raise_for_status()
                    data = resp.json()

                    # GPT image models всегда возвращают b64_json
                    item = (data.get("data") or [None])[0] or {}
                    if "b64_json" in item:
                        return base64.b64decode(item["b64_json"])
                    if "url" in item:
                        return await _download_image(item["url"], timeout=timeout)

                    raise ValueError(f"Unexpected images response: {data}")

                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    status = exc.response.status_code if exc.response else None
                    if status not in RETRYABLE_STATUS_CODES:
                        raise
                    if attempt >= settings.HTTP_RETRIES:
                        break
                    await asyncio.sleep(settings.HTTP_BACKOFF * (2**attempt))

                except (httpx.TimeoutException, httpx.TransportError, ValueError, KeyError) as exc:
                    last_error = exc
                    if attempt >= settings.HTTP_RETRIES:
                        break
                    await asyncio.sleep(settings.HTTP_BACKOFF * (2**attempt))

        raise RuntimeError("OpenAI image generation failed") from last_error

    # 1) Пытаемся основной моделью
    try:
        return await _call(model)
    except httpx.HTTPStatusError as e:
        resp = e.response
        body = resp.text if resp is not None else ""
        # 2) Fallback: если gpt-image-* требует verification — пробуем dall-e-3
        if resp is not None and resp.status_code == 403 and _is_verification_error(body):
            fallback_model = getattr(settings, "FALLBACK_IMAGE_MODEL", "dall-e-3")
            log.warning("Falling back to %s because org is not verified for %s", fallback_model, model)
            return await _call(fallback_model)
        raise
