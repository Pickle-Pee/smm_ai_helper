from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import httpx

from app.config import settings


async def chat(
    messages: List[Dict[str, str]],
    model: str,
    temperature: float = 0.7,
    max_output_tokens: int | None = None,
    response_format: Dict[str, Any] | None = None,
) -> tuple[str, Dict[str, Any]]:
    url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_output_tokens is not None:
        payload["max_tokens"] = max_output_tokens
    if response_format is not None:
        payload["response_format"] = response_format

    timeout = httpx.Timeout(settings.HTTP_TIMEOUT)
    last_error: Exception | None = None

    for attempt in range(settings.HTTP_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return content, usage
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            last_error = exc
            if attempt >= settings.HTTP_RETRIES:
                break
            await asyncio.sleep(settings.HTTP_BACKOFF * (2**attempt))

    raise RuntimeError("OpenAI chat failed") from last_error
