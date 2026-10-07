from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any, Dict, List, Tuple

import httpx

from app.config import settings, TOKEN_BUDGETS, MAX_OUTPUT_TOKENS_CAP
from app.model_generation_policy import ModuleOutputBudget, module_output_tokens

log = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class ModelResponseFailureReason(str, Enum):
    INCOMPLETE_MAX_OUTPUT_TOKENS = "incomplete_max_output_tokens"
    INCOMPLETE_CONTENT_FILTER = "incomplete_content_filter"
    INCOMPLETE_OTHER = "incomplete_other"
    REFUSAL = "refusal"
    INVALID_ENVELOPE = "invalid_envelope"


class ModelResponseError(ValueError):
    """Rejected provider envelope carrying only a bounded internal reason."""

    def __init__(self, reason: ModelResponseFailureReason):
        if not isinstance(reason, ModelResponseFailureReason):
            raise TypeError("ModelResponseError requires a ModelResponseFailureReason")
        self.reason = reason
        super().__init__(reason.value)


def _single_attempt_output(data: Any) -> str:
    if not isinstance(data, dict):
        raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE)
    if data.get("status") == "incomplete":
        details = data.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, dict) else None
        if reason == "max_output_tokens":
            failure = ModelResponseFailureReason.INCOMPLETE_MAX_OUTPUT_TOKENS
        elif reason == "content_filter":
            failure = ModelResponseFailureReason.INCOMPLETE_CONTENT_FILTER
        else:
            failure = ModelResponseFailureReason.INCOMPLETE_OTHER
        raise ModelResponseError(failure)
    if data.get("status") not in (None, "completed"):
        raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE)

    output = data.get("output", [])
    if not isinstance(output, list):
        raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE)
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE)
        if item.get("type") != "message":
            continue
        blocks = item.get("content", [])
        if not isinstance(blocks, list):
            raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE)
        for block in blocks:
            if not isinstance(block, dict):
                raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE)
            # Inspect refusal before accepting the convenience output_text field.
            if block.get("type") == "refusal":
                raise ModelResponseError(ModelResponseFailureReason.REFUSAL)
            if item.get("role") == "assistant" and block.get("type") == "output_text":
                text = block.get("text")
                if not isinstance(text, str):
                    raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE)
                texts.append(text)
    top = data.get("output_text")
    if top is not None and not isinstance(top, str):
        raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE)
    content = top.strip() if isinstance(top, str) and top.strip() else "\n".join(texts).strip()
    if not content:
        raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE)
    return content


def _log_response_rejection(
    reason: ModelResponseFailureReason, model: str, budget: int, data: Any
) -> None:
    fields: dict[str, Any] = {
        "reason": reason.value,
        "model": model,
        "max_output_tokens": budget,
    }
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict):
        output_tokens = usage.get("output_tokens")
        if type(output_tokens) is int and 0 <= output_tokens <= budget:
            fields["output_tokens"] = output_tokens
        details = usage.get("output_tokens_details")
        reasoning_tokens = details.get("reasoning_tokens") if isinstance(details, dict) else None
        reasoning_cap = fields.get("output_tokens", budget)
        if type(reasoning_tokens) is int and 0 <= reasoning_tokens <= reasoning_cap:
            fields["reasoning_tokens"] = reasoning_tokens
    log.warning(
        "Structured model response rejected " + " ".join(f"{key}=%s" for key in fields),
        *fields.values(),
        extra=fields,
    )


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
                raise ModelResponseError(ModelResponseFailureReason.REFUSAL)

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
    *,
    single_attempt: bool = False,
    output_budget: ModuleOutputBudget | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Responses API:
      POST /responses { model, input, max_output_tokens, text: { format: ... } }

    single_attempt is for durable graph execution: one bounded request, no
    schema fallback or token-budget expansion; JobExecution owns retries.
    Other callers retain the existing transport policy.
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

    if output_budget is not None:
        # Only the strict single-call module capability may select a larger
        # closed profile. Arbitrary max_output_tokens still uses the generic cap.
        if (not single_attempt or response_format is None
                or response_format.get("type") != "json_schema" or response_format.get("strict") is False):
            raise ValueError("Module output budget requires a strict single attempt")
        payload["max_output_tokens"] = module_output_tokens(output_budget)

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
        for attempt in range(1 if single_attempt else settings.HTTP_RETRIES + 1):
            try:
                resp = await client.post(url, headers=headers, json=payload)

                if single_attempt:
                    # Never log provider bodies or silently drop the response schema.
                    resp.raise_for_status()
                    data = None
                    try:
                        try:
                            data = resp.json()
                        except ValueError:
                            raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE) from None
                        content = _single_attempt_output(data)
                    except ModelResponseError as exc:
                        _log_response_rejection(exc.reason, model, payload["max_output_tokens"], data)
                        raise exc from None
                    return content, data.get("usage", {}) or {}

                if resp.status_code >= 400:
                    log.error("OpenAI responses error status=%s", resp.status_code)

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
                        raise RuntimeError("Responses returned no text even after retry")

                    return content2, usage2

                usage = data.get("usage", {}) or {}
                return content.strip(), usage

            except httpx.HTTPStatusError as exc:
                if single_attempt:
                    raise
                last_error = exc
                status = exc.response.status_code if exc.response else None
                if status not in RETRYABLE_STATUS_CODES:
                    raise
                if attempt >= settings.HTTP_RETRIES:
                    break
                await asyncio.sleep(settings.HTTP_BACKOFF * (2**attempt))

            except (httpx.TimeoutException, httpx.TransportError, ValueError, KeyError, RuntimeError) as exc:
                if single_attempt:
                    raise
                last_error = exc
                if attempt >= settings.HTTP_RETRIES:
                    break
                await asyncio.sleep(settings.HTTP_BACKOFF * (2**attempt))

    raise RuntimeError("OpenAI responses failed") from last_error
