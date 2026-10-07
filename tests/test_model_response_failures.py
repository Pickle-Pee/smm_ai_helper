"""Bounded provider diagnostics without another request or provider content."""
import asyncio
import logging
import traceback

import httpx
import pytest

from app.llm.openai_text import ModelResponseError, ModelResponseFailureReason, _extract_output_text, chat


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
    assert record.getMessage() == (
        f"Structured model response rejected reason={expected.value} "
        "model=configured-model max_output_tokens=4000 output_tokens=4000 reasoning_tokens=1800"
    )
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
    assert record.getMessage() == (
        "Structured model response rejected reason=incomplete_other "
        "model=configured-model max_output_tokens=4000"
    )
    assert not hasattr(record, "output_tokens")
    assert not hasattr(record, "reasoning_tokens")
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
