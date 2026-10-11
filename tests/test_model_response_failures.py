"""Bounded provider diagnostics without another request or provider content."""
import asyncio
import json
import logging
import traceback

import httpx
import pytest

from app.llm.openai_text import ModelResponseError, ModelResponseFailureReason, _extract_output_text, chat
from app.orchestration_runtime.worker import transient


def empty_incomplete():
    return {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
            "output": [], "usage": {"output_tokens": 0,
            "output_tokens_details": {"reasoning_tokens": 0}}}


@pytest.mark.parametrize("field,value", [
    ("output_tokens", None), ("output_tokens", False), ("output_tokens", "0"),
    ("output_tokens", 0.0), ("output_tokens", -1), ("output_tokens", 1),
    ("reasoning_tokens", None), ("reasoning_tokens", False), ("reasoning_tokens", "0"),
    ("reasoning_tokens", 0.0), ("reasoning_tokens", -1), ("reasoning_tokens", 1),
    ("output_tokens_details", None), ("output_tokens_details", []),
    ("output_tokens_details", {}), ("usage", None), ("usage", []), ("usage", {}),
    ("output", None), ("output", {}), ("output", ""), ("output", [{"type": "reasoning"}]),
])
def test_empty_incomplete_requires_confirmed_diagnostics(monkeypatch, field, value):
    data = empty_incomplete()
    if field == "reasoning_tokens":
        data["usage"]["output_tokens_details"][field] = value
    elif field in ("output_tokens", "output_tokens_details"):
        data["usage"][field] = value
    else:
        data[field] = value
    requests = install_response(monkeypatch, httpx.Response(200, json=data))
    with pytest.raises(ModelResponseError) as caught:
        call()
    assert caught.value.reason is ModelResponseFailureReason.INCOMPLETE_MAX_OUTPUT_TOKENS
    assert not transient(caught.value) and len(requests) == 1


@pytest.mark.parametrize("field", ["usage", "output_tokens", "output_tokens_details", "reasoning_tokens", "output"])
def test_empty_incomplete_missing_diagnostics_are_terminal(monkeypatch, field):
    data = empty_incomplete()
    container = (data["usage"]["output_tokens_details"] if field == "reasoning_tokens"
                 else data["usage"] if field in ("output_tokens", "output_tokens_details") else data)
    del container[field]
    install_response(monkeypatch, httpx.Response(200, json=data))
    with pytest.raises(ModelResponseError) as caught:
        call()
    assert caught.value.reason is ModelResponseFailureReason.INCOMPLETE_MAX_OUTPUT_TOKENS
    assert not transient(caught.value)


def test_confirmed_empty_anomaly_has_safe_diagnostics_and_one_request(monkeypatch, caplog):
    from app.config import settings
    from app.model_generation_policy import ModuleOutputBudget
    from app.orchestration_runtime.model_adapter import production_model_call
    data = empty_incomplete()
    data["usage"]["input_tokens"] = 123
    data["error"] = "PRIVATE_PROVIDER_BODY"
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "PRIVATE_API_KEY")
    schema = {"PRIVATE_SCHEMA": "секрет"}
    requests = install_response(monkeypatch, httpx.Response(
        200, json=data, headers={"x-request-id": "req_abc-123"}))
    kwargs = dict(instruction="PRIVATE_INSTRUCTIONS я", text="PRIVATE_INPUT я",
                  response_schema=schema, output_budget=ModuleOutputBudget.VIRTUAL_CMO)
    with pytest.raises(ModelResponseError) as caught:
        asyncio.run(production_model_call(**kwargs))
    assert caught.value.reason is ModelResponseFailureReason.INCOMPLETE_EMPTY_MAX_OUTPUT_TOKENS
    assert transient(caught.value) and len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["max_output_tokens"] == 16000
    assert payload["text"]["format"]["schema"] == schema and payload["text"]["format"]["strict"]
    record = next(r for r in caplog.records if r.name == "app.llm.openai_text")
    assert record.x_request_id == "req_abc-123" and record.input_tokens == 123
    assert record.input_text_bytes == len("PRIVATE_INPUT я".encode("utf-8"))
    assert record.instructions_bytes == len("PRIVATE_INSTRUCTIONS я".encode("utf-8"))
    assert record.json_schema_bytes == len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert "PRIVATE" not in caplog.text + str(record.__dict__)
    assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("value", [None, False, "PRIVATE_TOKENS", -1, 1.5, 2 ** 100])
def test_invalid_input_tokens_are_not_logged(monkeypatch, caplog, value):
    data = empty_incomplete()
    data["usage"]["input_tokens"] = value
    install_response(monkeypatch, httpx.Response(200, json=data,
        headers={"x-request-id": "PRIVATE header\tcontent"}))
    with pytest.raises(ModelResponseError):
        call()
    record = next(r for r in caplog.records if r.name == "app.llm.openai_text")
    assert not hasattr(record, "input_tokens") and not hasattr(record, "x_request_id")
    assert "PRIVATE" not in caplog.text


def install_response(monkeypatch, response):
    requests = []
    original = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        return response

    def client(**kwargs):
        return original(**kwargs, transport=httpx.MockTransport(handle), trust_env=False)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(logging.getLogger("app.llm.openai_text"), "disabled", False)
    return requests


def call():
    return asyncio.run(chat(
        [{"role": "user", "content": "PRIVATE_PROMPT_USER_EVIDENCE"}],
        "configured-model", max_output_tokens=4000,
        response_format={"type": "json_schema", "schema": {"PRIVATE_SCHEMA": True}},
        single_attempt=True,
    ))


@pytest.mark.parametrize("top", [False, True])
def test_completed_response_preserves_content_and_usage(monkeypatch, top):
    data = {"status": "completed", "usage": {"output_tokens": 8}}
    if top:
        data["output_text"] = ' {"ok":true} '
    else:
        data["output"] = [{"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": ' {"ok":true} '},
        ]}]
    requests = install_response(monkeypatch, httpx.Response(200, json=data))
    assert call() == ('{"ok":true}', {"output_tokens": 8})
    assert len(requests) == 1


@pytest.mark.parametrize("provider_reason,expected", [
    ("max_output_tokens", ModelResponseFailureReason.INCOMPLETE_MAX_OUTPUT_TOKENS),
    ("content_filter", ModelResponseFailureReason.INCOMPLETE_CONTENT_FILTER),
    ("PRIVATE_PROVIDER_REASON", ModelResponseFailureReason.INCOMPLETE_OTHER),
    (None, ModelResponseFailureReason.INCOMPLETE_OTHER),
    ({"PRIVATE": "value"}, ModelResponseFailureReason.INCOMPLETE_OTHER),
])
def test_incomplete_response_has_safe_reason_and_usage(monkeypatch, caplog, provider_reason, expected):
    requests = install_response(monkeypatch, httpx.Response(200, json={
        "status": "incomplete", "incomplete_details": {"reason": provider_reason},
        "output_text": "PRIVATE_RAW_OUTPUT", "error": "PRIVATE_PROVIDER_ERROR",
        "usage": {"output_tokens": 4000, "output_tokens_details": {"reasoning_tokens": 1800}},
    }))
    with pytest.raises(ModelResponseError) as caught:
        call()
    assert caught.value.reason is expected
    assert str(caught.value) == expected.value
    assert len(requests) == 1
    record = next(r for r in caplog.records if r.name == "app.llm.openai_text")
    assert record.getMessage().startswith(
        f"Structured model response rejected reason={expected.value} "
        "model=configured-model max_output_tokens=4000"
    )
    assert record.output_tokens == 4000 and record.reasoning_tokens == 1800
    assert record.exc_info is None
    assert "PRIVATE" not in caplog.text
    assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("usage", [
    {"output_tokens": True, "output_tokens_details": {"reasoning_tokens": False}},
    {"output_tokens": "PRIVATE_TOKENS", "output_tokens_details": {"reasoning_tokens": "PRIVATE"}},
    {"output_tokens": 1.5, "output_tokens_details": {"reasoning_tokens": -1}},
    {"output_tokens": -1, "output_tokens_details": "PRIVATE_DETAILS"},
    {"output_tokens": {}, "output_tokens_details": []},
    {"output_tokens": 10 ** 1000, "output_tokens_details": {"reasoning_tokens": 10 ** 1000}},
    "PRIVATE_USAGE", None,
])
def test_usage_logging_requires_nonnegative_integers(monkeypatch, caplog, usage):
    install_response(monkeypatch, httpx.Response(200, json={
        "status": "incomplete", "usage": usage,
    }))
    with pytest.raises(ModelResponseError):
        call()
    record = next(r for r in caplog.records if r.name == "app.llm.openai_text")
    assert record.getMessage().startswith(
        "Structured model response rejected reason=incomplete_other "
        "model=configured-model max_output_tokens=4000"
    )
    assert not hasattr(record, "output_tokens")
    assert not hasattr(record, "reasoning_tokens")
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize("usage,output_state,reasoning_state", [
    ({"output_tokens": 0, "output_tokens_details": {"reasoning_tokens": 0}}, "reported", "reported"),
    ({}, "missing", "missing"),
    ({"output_tokens": 0}, "reported", "missing"),
    ({"output_tokens": None, "output_tokens_details": {"reasoning_tokens": None}}, "null", "null"),
    ({"output_tokens": True, "output_tokens_details": {"reasoning_tokens": "PRIVATE"}}, "invalid", "invalid"),
])
def test_zero_usage_is_not_missing_and_metadata_is_content_free(monkeypatch, caplog, usage, output_state, reasoning_state):
    requests = install_response(monkeypatch, httpx.Response(200, json={
        "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
        "usage": usage, "output_text": "PRIVATE_TEXT",
        "output": [{"type": "reasoning", "status": "completed", "summary": "PRIVATE_REASONING"},
                   {"type": "message", "status": "incomplete", "id": "PRIVATE_ID",
                    "content": [{"type": "output_text", "text": "PRIVATE_PARTIAL"}]}],
    }))
    with pytest.raises(ModelResponseError) as caught:
        call()
    assert caught.value.reason is ModelResponseFailureReason.INCOMPLETE_MAX_OUTPUT_TOKENS
    assert len(requests) == 1
    record = next(r for r in caplog.records if r.name == "app.llm.openai_text")
    assert record.response_status == "incomplete"
    assert record.output_tokens_state == output_state
    assert record.reasoning_tokens_state == reasoning_state
    assert hasattr(record, "output_tokens") == (output_state == "reported")
    assert hasattr(record, "reasoning_tokens") == (reasoning_state == "reported")
    if output_state == "reported":
        assert record.output_tokens == 0
    if reasoning_state == "reported":
        assert record.reasoning_tokens == 0
    assert record.output_items_count == 2
    assert record.reasoning_items == record.message_items == 1
    assert record.completed_items == record.incomplete_items == 1
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize("extra,state", [({}, "missing"), ({"usage": None}, "null"),
    ({"usage": {}}, "present"), ({"usage": "PRIVATE"}, "invalid")])
def test_usage_container_presence_is_explicit(monkeypatch, caplog, extra, state):
    install_response(monkeypatch, httpx.Response(200, json={"status": "incomplete", **extra}))
    with pytest.raises(ModelResponseError):
        call()
    record = next(r for r in caplog.records if r.name == "app.llm.openai_text")
    assert record.usage_state == state
    assert not hasattr(record, "output_tokens")
    assert not hasattr(record, "reasoning_tokens")
    assert "PRIVATE" not in caplog.text


def test_item_diagnostics_are_bounded_and_unknown_labels_never_logged(monkeypatch, caplog):
    requests = install_response(monkeypatch, httpx.Response(200, json={
        "status": "PRIVATE_STATUS", "output": [
            {"type": "PRIVATE_TYPE", "status": "PRIVATE_STATUS", "summary": "PRIVATE_SUMMARY"}
        ] * 100, "usage": {"output_tokens": 10 ** 1000},
    }))
    with pytest.raises(ModelResponseError):
        call()
    record = next(r for r in caplog.records if r.name == "app.llm.openai_text")
    assert record.response_status == "unknown"
    assert record.output_items_count == 32 and record.output_items_truncated
    assert record.reasoning_items == record.message_items == record.completed_items == 0
    assert len(requests) == 1
    assert "PRIVATE" not in caplog.text


def test_reasoning_usage_cannot_exceed_output_usage(monkeypatch, caplog):
    install_response(monkeypatch, httpx.Response(200, json={
        "status": "incomplete", "usage": {
            "output_tokens": 10, "output_tokens_details": {"reasoning_tokens": 11},
        },
    }))
    with pytest.raises(ModelResponseError):
        call()
    record = next(r for r in caplog.records if r.name == "app.llm.openai_text")
    assert record.output_tokens == 10
    assert not hasattr(record, "reasoning_tokens")


def test_refusal_precedes_output_text_shortcut_and_never_leaks(monkeypatch, caplog):
    requests = install_response(monkeypatch, httpx.Response(200, json={
        "status": "completed", "output_text": "PRIVATE_RAW_OUTPUT",
        "output": [{"type": "message", "role": "assistant", "content": [
            {"type": "refusal", "refusal": "PRIVATE_REFUSAL"},
        ]}],
    }))
    with pytest.raises(ModelResponseError) as caught:
        call()
    assert caught.value.reason is ModelResponseFailureReason.REFUSAL
    assert caught.value.__cause__ is None
    assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
    assert "PRIVATE" not in caplog.text
    assert len(requests) == 1


@pytest.mark.parametrize("data", [
    None, [], "PRIVATE_ENVELOPE", {},
    {"status": "failed", "error": {"message": "PRIVATE_ERROR"}},
    {"status": []}, {"output": "PRIVATE_OUTPUT"}, {"output": [None]},
    {"output": [{"type": "message", "content": "PRIVATE_CONTENT"}]},
    {"output": [{"type": "message", "content": [None]}]},
    {"output": [{"type": "message", "role": "assistant", "content": [
        {"type": "output_text", "text": {"PRIVATE": "text"}},
    ]}]},
    {"output_text": {"PRIVATE": "text"}}, {"output_text": "   "},
])
def test_invalid_2xx_envelope_is_safe_and_single_attempt(monkeypatch, caplog, data):
    requests = install_response(monkeypatch, httpx.Response(200, json=data))
    with pytest.raises(ModelResponseError) as caught:
        call()
    assert caught.value.reason is ModelResponseFailureReason.INVALID_ENVELOPE
    assert "PRIVATE" not in str(caught.value)
    assert "PRIVATE" not in caplog.text
    assert len(requests) == 1


def test_invalid_json_suppresses_provider_decoder_traceback(monkeypatch, caplog):
    requests = install_response(monkeypatch, httpx.Response(200, content=b"PRIVATE_INVALID_JSON"))
    with pytest.raises(ModelResponseError) as caught:
        call()
    assert caught.value.reason is ModelResponseFailureReason.INVALID_ENVELOPE
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert "PRIVATE" not in "".join(traceback.format_exception(caught.value))
    assert "PRIVATE" not in caplog.text
    assert len(requests) == 1


def test_http_schema_rejection_remains_http_error(monkeypatch, caplog):
    requests = install_response(monkeypatch, httpx.Response(400, json={
        "error": {"param": "text.format", "code": "invalid_request_error", "message": "PRIVATE_SCHEMA_ERROR"},
    }))
    with pytest.raises(httpx.HTTPStatusError):
        call()
    assert len(requests) == 1
    assert "Structured model response rejected" not in caplog.text
    assert "PRIVATE" not in caplog.text


def test_exception_rejects_arbitrary_provider_text():
    with pytest.raises(TypeError) as caught:
        ModelResponseError("PRIVATE_PROVIDER_TEXT")
    assert "PRIVATE" not in str(caught.value)


def test_legacy_refusal_exception_is_also_bounded():
    with pytest.raises(ModelResponseError) as caught:
        _extract_output_text({"output": [{"type": "message", "role": "assistant", "content": [
            {"type": "refusal", "refusal": "PRIVATE_PROVIDER_TEXT"},
        ]}]})
    assert caught.value.reason is ModelResponseFailureReason.REFUSAL
    assert "PRIVATE" not in str(caught.value)
