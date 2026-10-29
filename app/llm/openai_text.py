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

from app.llm.telemetry import correlation_fields, cancellation_outcome, safe_label, safe_provider_id, provider_hooks
from app.config import settings, TOKEN_BUDGETS, MAX_OUTPUT_TOKENS_CAP
from app.model_generation_policy import ModuleOutputBudget, module_output_tokens

log = logging.getLogger(__name__)

# HTTP 408 may describe an unknown execution outcome; leave retry to the owner.
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_LEGACY_POSTS = 3


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
    if data.get("status") != "completed":
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
        if item.get("status") not in (None, "completed"):
            raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE)
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


async def _post_response(client, url, *, headers, payload, single_attempt):
    """Observe exactly one POST using the same envelope barrier as the caller."""
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
    hooks = provider_hooks()
    fields["retry_owner"] = "workflow" if hooks else "graph" if single_attempt else "transport"
    fields["retry_decision"] = "owner_pending" if single_attempt or hooks else "transport_policy"
    if hooks:
        await hooks[0](fields)
    _log_provider_event({**fields, "event": "started"})
    started = time.monotonic()
    response = None
    data = None
    reason = None
    primary_error = None
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
                _single_attempt_output(data)
                outcome = "success"
            except ModelResponseError as exc:
                reason = exc.reason
                outcome = "rejected"
            except (ValueError, KeyError, TypeError, AttributeError):
                # Malformed provider data must not escape the bounded diagnostics contract.
                reason = ModelResponseFailureReason.INVALID_ENVELOPE
                outcome = "rejected"
        if hooks:
            # Establish the provider failure before saving diagnostics so a
            # receipt outage cannot replace the original HTTP/envelope error.
            response.raise_for_status()
            if reason is not None:
                raise ModelResponseError(reason)
        return response
    except (httpx.TimeoutException, TimeoutError) as exc:
        primary_error = exc
        outcome = "timeout"
        raise
    except asyncio.CancelledError as exc:
        primary_error = exc
        outcome = cancellation_outcome()
        raise
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        fields.update(
            event="finished", outcome=outcome,
            duration_ms=min(max(round((time.monotonic() - started) * 1000), 0), 2 ** 31 - 1),
            http_status=response.status_code if response is not None else None,
            response_received=response is not None,
            # Reported zero is a counter, never proof that a POST was free.
            billing_outcome="unknown",
            outcome_unknown=response is None or response.status_code == 408,
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
            fields["request_id"] = request_id
        details = data.get("incomplete_details") if isinstance(data, dict) else None
        incomplete = details.get("reason") if isinstance(details, dict) else None
        fields["incomplete_reason"] = (incomplete if type(incomplete) is str and incomplete in
            ("max_output_tokens", "content_filter") else "other" if incomplete is not None else None)
        fields["status"] = fields["response_status"]
        fields["failure_reason"] = reason.value if reason is not None else None
        # Add normalized states without changing v1 counters consumed by operators.
        for counter in ("input_tokens", "output_tokens", "reasoning_tokens"):
            state = fields[counter + "_state"]
            fields[counter + "_usage_state"] = (
                "unknown" if response is None else "reported_zero" if state == "reported" and fields[counter] == 0
                else "reported" if state == "reported" else "missing" if state == "missing" else "unknown")
        states = [fields[c + "_usage_state"] for c in ("input_tokens", "output_tokens", "reasoning_tokens")]
        fields["token_usage_state"] = (
            "unknown" if response is None else "reported_zero" if all(s == "reported_zero" for s in states)
            else "reported" if all(s in {"reported", "reported_zero"} for s in states)
            else "missing" if all(s == "missing" for s in states) else "unknown")
        if reason is not None:
            _log_response_rejection(reason, payload["model"], payload["max_output_tokens"], data,
                                    request_id=request_id, payload=payload, telemetry=fields)
        else:
            _log_provider_event(fields, level=logging.INFO if outcome == "success" else logging.WARNING)
        if hooks:
            try:
                await hooks[1](fields)
            except Exception as diagnostic_error:
                log.error("Provider receipt persistence failed provider_call_id=%s error_type=%s",
                          fields["provider_call_id"], type(diagnostic_error).__name__)
                if primary_error is None:
                    # Never accept a successful result without a durable receipt.
                    raise
                primary_error.add_note("Provider receipt persistence failed; reservation remains unresolved.")
                # Keep the primary exception in flight. The durable reservation
                # remains conservative and the workflow owner decides recovery.


def _extract_output_text(data: Dict[str, Any]) -> str:
    """Compatibility entrypoint; all callers share the completed-envelope barrier."""
    return _single_attempt_output(data)


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
    Legacy calls allow at most three POSTs, bounded by HTTP_RETRIES + 1.
    Only explicit retryable HTTP errors and the known unsupported-temperature
    rejection can repeat. Every POST retains its initial token cap and schema.
    Rejected envelopes and unknown transport outcomes never retry locally.
    The returned usage dictionary belongs to the accepted response; receipts
    for every POST (including rejected ones) are kept by existing telemetry.
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

    # A governed workflow accounts for every POST, including nested capabilities.
    single_attempt = single_attempt or provider_hooks() is not None
    timeout = httpx.Timeout(settings.HTTP_TIMEOUT)
    posts = 1 if single_attempt else min(MAX_LEGACY_POSTS, max(1, settings.HTTP_RETRIES + 1))

    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(posts):
            # The payload is never enlarged; the one loop accounts for every POST.
            # Do not catch transport errors: a lost response has an unknown outcome.
            resp = await _post_response(client, url, headers=headers, payload=payload,
                                        single_attempt=single_attempt)
            if not single_attempt and resp.status_code == 400 and "temperature" in payload:
                try:
                    error = resp.json().get("error")
                except (ValueError, AttributeError):
                    error = None
                if (isinstance(error, dict) and error.get("param") == "temperature"
                        and error.get("code") == "unsupported_value" and attempt + 1 < posts):
                    # Existing, narrow compatibility policy for a known rejection.
                    # It consumes a normal attempt and never changes text.format.
                    payload.pop("temperature")
                    continue
            if (not single_attempt and resp.status_code in RETRYABLE_STATUS_CODES
                    and attempt + 1 < posts):
                await asyncio.sleep(settings.HTTP_BACKOFF * (2**attempt))
                continue
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                raise ModelResponseError(ModelResponseFailureReason.INVALID_ENVELOPE) from None
            content = _single_attempt_output(data)
            usage = data.get("usage")
            return content, usage if isinstance(usage, dict) else {}
