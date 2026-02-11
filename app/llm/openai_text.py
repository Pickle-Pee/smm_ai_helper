from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Tuple

import httpx

from app.config import settings, TOKEN_BUDGETS, MAX_OUTPUT_TOKENS_CAP

log = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _extract_output_text(data: Dict[str, Any]) -> str:
    """
    Responses API возвращает items в data["output"].
    Нам нужен текст из message(role=assistant)->content(type=output_text).

    Важно: иногда ответ может быть incomplete и содержать только reasoning.
    В этом случае возвращаем пустую строку, чтобы chat() мог сделать ретрай.
    """
    top = data.get("output_text")
    if isinstance(top, str) and top.strip():
        return top.strip()

    output = data.get("output") or []
    texts: list[str] = []

    for item in output:
        if item.get("type") != "message":
            continue
        if item.get("role") != "assistant":
            continue

        for block in (item.get("content") or []):
            btype = block.get("type")
            if btype == "output_text":
                t = block.get("text")
                if t:
                    texts.append(t)
            elif btype == "refusal":
                refusal = block.get("refusal") or "Model refused to answer"
                raise ValueError(refusal)

    return "\n".join(texts).strip()


def _is_incomplete_max_tokens(data: Dict[str, Any]) -> bool:
    return (
        data.get("status") == "incomplete"
        and (data.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
    )


def _choose_budget(task: str | None, response_format: Dict[str, Any] | None) -> int:
    if response_format is not None:
        if task is None:
            return TOKEN_BUDGETS.get("facts_json", 1500)
        return TOKEN_BUDGETS.get(task, TOKEN_BUDGETS.get("facts_json", 1500))

    if task is None:
        return TOKEN_BUDGETS.get("default", 1200)

    return TOKEN_BUDGETS.get(task, TOKEN_BUDGETS.get("default", 1200))


def _clamp_budget(n: int) -> int:
    return max(256, min(int(n), int(MAX_OUTPUT_TOKENS_CAP)))


async def chat(
    messages: List[Dict[str, str]],
    model: str,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    response_format: Dict[str, Any] | None = None,
    task: str | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Responses API:
      POST /responses { model, input, max_output_tokens, text: { format: ... } }
    """
    url = f"{settings.OPENAI_BASE_URL.rstrip('/')}/responses"
    headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}"}

    payload: Dict[str, Any] = {
        "model": model,
        "input": messages,
        # "store": False,
    }

    if model.startswith("gpt-5"):
        payload.setdefault("reasoning", {"effort": "low"})

    if temperature is not None:
        payload["temperature"] = temperature

    min_budget = _choose_budget(task, response_format)

    if max_output_tokens is None:
        payload["max_output_tokens"] = _clamp_budget(min_budget)
    else:
        payload["max_output_tokens"] = _clamp_budget(max(int(max_output_tokens), int(min_budget)))

    if response_format is not None:
        fmt = dict(response_format)

        if fmt.get("type") == "json_schema":
            if "name" not in fmt or not fmt.get("name"):
                fmt["name"] = task or "structured_output"
            if "strict" not in fmt:
                fmt["strict"] = True

        payload["text"] = {"format": fmt}
        payload["reasoning"] = {"effort": "low"}

    timeout = httpx.Timeout(settings.HTTP_TIMEOUT)
    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(settings.HTTP_RETRIES + 1):
            try:
                resp = await client.post(url, headers=headers, json=payload)

                if resp.status_code >= 400:
                    body = resp.text
                    log.error("OpenAI responses error status=%s body=%s", resp.status_code, body[:4000])

                    try:
                        err = (resp.json() or {}).get("error", {}) or {}
                        param = err.get("param")
                        code = err.get("code")

                        if (
                            resp.status_code == 400
                            and param == "temperature"
                            and code == "unsupported_value"
                            and "temperature" in payload
                        ):
                            payload.pop("temperature", None)
                            resp = await client.post(url, headers=headers, json=payload)

                        elif (
                            resp.status_code == 400
                            and (param in {"text", "text.format"} or "text" in str(param))
                            and code in {"unsupported_value", "invalid_request_error"}
                            and "text" in payload
                        ):
                            payload.pop("text", None)
                            resp = await client.post(url, headers=headers, json=payload)

                        elif resp.status_code not in RETRYABLE_STATUS_CODES:
                            resp.raise_for_status()

                    except ValueError:
                        if resp.status_code not in RETRYABLE_STATUS_CODES:
                            resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()

                content = _extract_output_text(data)

                if _is_incomplete_max_tokens(data) or not content:
                    prev = int(payload.get("max_output_tokens") or 0)
                    payload["max_output_tokens"] = max(2000, prev * 6 if prev else 2000)
                    payload["reasoning"] = {"effort": "low"}

                    resp2 = await client.post(url, headers=headers, json=payload)
                    resp2.raise_for_status()
                    data2 = resp2.json()

                    content2 = _extract_output_text(data2).strip()
                    usage2 = data2.get("usage", {}) or {}

                    if not content2:
                        raise RuntimeError(f"Responses returned no text even after retry: {data2}")

                    return content2, usage2

                usage = data.get("usage", {}) or {}
                return content.strip(), usage

            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code if exc.response else None
                if status not in RETRYABLE_STATUS_CODES:
                    raise
                if attempt >= settings.HTTP_RETRIES:
                    break
                await asyncio.sleep(settings.HTTP_BACKOFF * (2**attempt))

            except (httpx.TimeoutException, httpx.TransportError, ValueError, KeyError, RuntimeError) as exc:
                last_error = exc
                if attempt >= settings.HTTP_RETRIES:
                    break
                await asyncio.sleep(settings.HTTP_BACKOFF * (2**attempt))

    raise RuntimeError("OpenAI responses failed") from last_error
