from __future__ import annotations

import asyncio
import base64
from typing import Any, Dict

import httpx

from app.config import settings


async def generate_image(
    prompt: str,
    size: str,
    model: str,
    quality: str = "standard",
) -> bytes:
    url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/images/generations"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "response_format": "b64_json",
    }

    timeout = httpx.Timeout(settings.HTTP_TIMEOUT)
    last_error: Exception | None = None

    for attempt in range(settings.HTTP_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                b64_data = data["data"][0]["b64_json"]
                return base64.b64decode(b64_data)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            last_error = exc
            if attempt >= settings.HTTP_RETRIES:
                break
            await asyncio.sleep(settings.HTTP_BACKOFF * (2**attempt))

    raise RuntimeError("OpenAI image generation failed") from last_error
