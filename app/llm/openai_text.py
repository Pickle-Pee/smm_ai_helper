from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Tuple

import httpx

from app.config import settings

log = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


async def chat(
    messages: List[Dict[str, str]],
    model: str,
    temperature: float | None = None,          # <-- важно
    max_output_tokens: int | None = None,
) -> Tuple[str, Dict[str, Any]]:
    url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    # температуру добавляем только когда это нужно/разрешено
    if temperature is not None:
        payload["temperature"] = temperature

    if max_output_tokens is not None:
        payload["max_completion_tokens"] = max_output_tokens

    timeout = httpx.Timeout(settings.HTTP_TIMEOUT)
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(settings.HTTP_RETRIES + 1):
            try:
                resp = await client.post(url, headers=headers, json=payload)

                if resp.status_code >= 400:
                    body = resp.text
                    log.error("OpenAI chat error status=%s body=%s", resp.status_code, body[:4000])

                    # fallback: если модель не принимает temperature
                    try:
                        err = resp.json().get("error", {})
                        if (
                            resp.status_code == 400
                            and err.get("param") == "temperature"
                            and err.get("code") == "unsupported_value"
                            and "temperature" in payload
                        ):
                            payload.pop("temperature", None)
                            # повторить один раз без temperature
                            resp = await client.post(url, headers=headers, json=payload)
                            if resp.status_code >= 400:
                                log.error(
                                    "OpenAI chat error after removing temperature status=%s body=%s",
                                    resp.status_code,
                                    resp.text[:4000],
                                )
                            resp.raise_for_status()
                        else:
                            # 4xx (кроме 408/429) не ретраим
                            if resp.status_code not in RETRYABLE_STATUS_CODES:
                                resp.raise_for_status()
                    except ValueError:
                        # не смогли распарсить json ошибки — просто падаем/ретраим по политике ниже
                        if resp.status_code not in RETRYABLE_STATUS_CODES:
                            resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()

                choices = data.get("choices") or []
                if not choices:
                    raise ValueError(f"No choices in response: {data}")

                msg = choices[0].get("message") or {}
                content = msg.get("content")
                if content is None:
                    raise ValueError(f"No message.content in response: {data}")

                usage = data.get("usage", {}) or {}
                return content, usage

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

    raise RuntimeError("OpenAI chat failed") from last_error
