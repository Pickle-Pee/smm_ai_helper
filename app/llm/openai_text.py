from __future__ import annotations

import asyncio
import json
import hashlib
import time
import uuid
import logging
from enum import Enum
from typing import Any, Dict, List, Tuple

import httpx

from app.llm.telemetry import correlation_fields, cancellation_outcome, safe_label, safe_provider_id
from app.config import settings, TOKEN_BUDGETS, MAX_OUTPUT_TOKENS_CAP
from app.model_generation_policy import ModuleOutputBudget, module_output_tokens
from app.llm import controlled_live

log = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class ModelResponseFailureReason(str, Enum):
    INCOMPLETE_EMPTY_MAX_OUTPUT_TOKENS = "incomplete_empty_max_output_tokens"
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
            usage = data.get("usage")
            details = usage.get("output_tokens_details") if isinstance(usage, dict) else None
            output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
            reasoning_tokens = details.get("reasoning_tokens") if isinstance(details, dict) else None
            output = data.get("output")
            if (type(output_tokens) is int and output_tokens == 0
                    and type(reasoning_tokens) is int and reasoning_tokens == 0
                    and isinstance(output, list) and not output):
                failure = ModelResponseFailureReason.INCOMPLETE_EMPTY_MAX_OUTPUT_TOKENS
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
    reason: ModelResponseFailureReason, model: str, budget: int, data: Any,
    *, request_id: str | None, payload: dict[str, Any], telemetry: dict[str, Any],
) -> None:
    fields: dict[str, Any] = {
        "reason": reason.value,
        "model": safe_label(model),
        "max_output_tokens": budget,
    }
    # Provider correlation IDs are bounded opaque labels, never arbitrary headers.
    if safe_provider_id(request_id, "request") is not None:
        fields["x_request_id"] = request_id
    fields["input_text_bytes"] = sum(
        len(message["content"].encode("utf-8")) for message in payload["input"]
        if message.get("role") not in ("system", "developer")
    )
    fields["instructions_bytes"] = sum(
        len(message["content"].encode("utf-8")) for message in payload["input"]
        if message.get("role") in ("system", "developer")
    )
    schema = payload.get("text", {}).get("format", {}).get("schema")
    fields["json_schema_bytes"] = (
        len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if schema is not None else 0
    )
    fields.update(_response_metadata(data, budget))
    fields.update(telemetry)
    log.warning(
        "Structured model response rejected " + " ".join(f"{key}=%s" for key in fields),
        *fields.values(),
        extra=fields,
    )


def _response_metadata(data: Any, budget: int) -> dict[str, Any]:
    """Closed labels and capped item counts only; never serialize provider values."""
    if not isinstance(data, dict):
        data = {}
        invalid = True
    else:
        invalid = False
    status = data.get("status")
    fields: dict[str, Any] = {
        "response_status": "invalid" if invalid else status if type(status) is str and status in (
            "completed", "incomplete", "failed", "in_progress", "queued", "cancelled"
        ) else "unknown",
        "usage_state": "missing" if "usage" not in data else (
            "null" if data["usage"] is None else (
                "present" if isinstance(data["usage"], dict) else "invalid")),
    }
    usage = data.get("usage")
    output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
    reasoning_cap = output_tokens if type(output_tokens) is int and 0 <= output_tokens <= budget else budget
    fields["output_tokens_details_state"] = (
        "missing" if not isinstance(usage, dict) or "output_tokens_details" not in usage else
        "null" if usage["output_tokens_details"] is None else
        "present" if isinstance(usage["output_tokens_details"], dict) else "invalid"
    )
    for name, container, cap in (
        ("input_tokens", usage, 2 ** 31 - 1),
        ("total_tokens", usage, 2 ** 31 - 1),
        ("output_tokens", usage, budget),
        ("reasoning_tokens", usage.get("output_tokens_details") if isinstance(usage, dict) else None, reasoning_cap),
    ):
        fields[name + "_state"] = (
            "missing" if not isinstance(container, dict) or name not in container else
            "null" if container[name] is None else
            "reported" if type(container[name]) is int and 0 <= container[name] <= cap else
            "invalid"
        )
        if fields[name + "_state"] == "reported":
            fields[name] = container[name]
    output = data.get("output")
    fields["output_items_state"] = "missing" if "output" not in data else (
        "present" if isinstance(output, list) else "invalid")
    if isinstance(output, list):
        # Inspect a bounded prefix, even for a malformed or oversized envelope.
        fields["output_items_count"] = min(len(output), 32)
        fields["output_items_truncated"] = len(output) > 32
        for item_type in ("reasoning", "message"):
            fields[item_type + "_items"] = sum(
                isinstance(item, dict) and item.get("type") == item_type for item in output[:32])
        for item_status in ("completed", "incomplete", "in_progress"):
            fields[item_status + "_items"] = sum(
                isinstance(item, dict) and item.get("status") == item_status for item in output[:32])
    return fields


def _log_provider_event(fields, *, level=logging.INFO):
    # Serialize only the closed contract; no request/response/exception objects.
    log.log(level, "LLM provider request " + " ".join(f"{key}=%s" for key in fields),
            *fields.values(), extra=fields)


async def _post_response(client, url, *, headers, payload, single_attempt, allow_output_retry=True):
    """Observe exactly one existing POST; never change payloads or retry policy."""
    schema = payload.get("text", {}).get("format", {}).get("schema")
    fields = {
        "telemetry_version": "llm_provider_request.v1",
        "request_mode": "single_attempt" if single_attempt else "legacy",
        "provider_call_id": uuid.uuid4().hex,
        **correlation_fields(),
        "model": safe_label(payload["model"]),
        "max_output_tokens": payload["max_output_tokens"],
        "schema_fingerprint": hashlib.sha256(json.dumps(
            schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest() if schema is not None else None,
    }
    gate = controlled_live.admission() if settings.CONTROLLED_LIVE_ENABLED else None
    receipt = await gate.reserve(payload) if gate is not None else None
    _log_provider_event({**fields, "event": "started"})
    started = time.monotonic()
    response = None
    data = None
    reason = None
    outcome = "transport_error"
    try:
        response = await client.post(url, headers=headers, json=payload)
        try:
            data = response.json()
        except ValueError:
            pass
        if not response.is_success:
            # raise_for_status rejects all non-2xx statuses, including redirects.
            outcome = "http_error"
        else:
            try:
                if single_attempt:
                    _single_attempt_output(data)
                    outcome = "success"
                else:
                    content = _extract_output_text(data)
                    if allow_output_retry and _legacy_output_needs_retry(data, content):
                        outcome = "retry_requested"
                    elif content:
                        outcome = "success"
                    else:
                        reason = ModelResponseFailureReason.INVALID_ENVELOPE
                        outcome = "rejected"
            except ModelResponseError as exc:
                reason = exc.reason
                outcome = "rejected"
            except (ValueError, KeyError, TypeError, AttributeError):
                # Observation must not replace the legacy caller's error/retry path.
                reason = ModelResponseFailureReason.INVALID_ENVELOPE
                outcome = "rejected"
        return response
    except (httpx.TimeoutException, TimeoutError):
        outcome = "timeout"
        raise
    except asyncio.CancelledError:
        outcome = cancellation_outcome()
        raise
    finally:
        if gate is not None:
            await gate.finish(receipt, success=outcome == "success")
        fields.update(
            event="finished", outcome=outcome,
            duration_ms=min(max(round((time.monotonic() - started) * 1000), 0), 2 ** 31 - 1),
            http_status=response.status_code if response is not None else None,
            response_received=response is not None,
        )
        fields.update(_response_metadata(data, payload["max_output_tokens"]))
        if response is None:
            # No envelope was observed; distinguish from missing usage in an envelope.
            fields["response_status"] = "unavailable"
            fields["usage_state"] = "unavailable"
        response_id = data.get("id") if isinstance(data, dict) else None
        if safe_provider_id(response_id, "response") is not None:
            fields["response_id"] = response_id
        request_id = response.headers.get("x-request-id") if response is not None else None
        if safe_provider_id(request_id, "request") is not None:
            fields["x_request_id"] = request_id
        details = data.get("incomplete_details") if isinstance(data, dict) else None
        incomplete = details.get("reason") if isinstance(details, dict) else None
        fields["incomplete_reason"] = (incomplete if type(incomplete) is str and incomplete in
            ("max_output_tokens", "content_filter") else "other" if incomplete is not None else None)
        if reason is not None:
            _log_response_rejection(reason, payload["model"], payload["max_output_tokens"], data,
                                    request_id=request_id, payload=payload, telemetry=fields)
        else:
            _log_provider_event(fields, level=logging.INFO if outcome == "success" else logging.WARNING)


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


def _legacy_output_needs_retry(data: Dict[str, Any], content: str) -> bool:
    return _is_incomplete_max_tokens(data) or not content


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
    if settings.CONTROLLED_LIVE_ENABLED:
        single_attempt = True
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
                resp = await _post_response(client, url, headers=headers, payload=payload,
                                            single_attempt=single_attempt)

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
                            resp = await _post_response(client, url, headers=headers, payload=payload,
                                                        single_attempt=False)

                        elif (
                            resp.status_code == 400
                            and (param in {"text", "text.format"} or "text" in str(param))
                            and code in {"unsupported_value", "invalid_request_error"}
                            and "text" in payload
                        ):
                            payload.pop("text", None)
                            resp = await _post_response(client, url, headers=headers, payload=payload,
                                                        single_attempt=False)

                        elif resp.status_code not in RETRYABLE_STATUS_CODES:
                            resp.raise_for_status()

                    except ValueError:
                        if resp.status_code not in RETRYABLE_STATUS_CODES:
                            resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()

                content = _extract_output_text(data)

                if _legacy_output_needs_retry(data, content):
                    prev = int(payload.get("max_output_tokens") or 0)
                    payload["max_output_tokens"] = max(2000, prev * 6 if prev else 2000)
                    payload["reasoning"] = {"effort": "low"}

                    resp2 = await _post_response(client, url, headers=headers, payload=payload,
                                                single_attempt=False, allow_output_retry=False)
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
