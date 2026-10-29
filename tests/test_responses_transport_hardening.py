"""Offline wire regressions: every request uses the real HTTPX serializer."""
import asyncio
import json
import logging
import socket

import httpx
import pytest

from app.config import settings, MAX_OUTPUT_TOKENS_CAP
from app.llm.openai_text import chat, ModelResponseError, ModelResponseFailureReason

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"], "additionalProperties": False}
FORMAT = {"type": "json_schema", "name": "transport_test", "strict": True, "schema": SCHEMA}
MESSAGES = [{"role": "user", "content": "PRIVATE_INPUT"}]


@pytest.fixture(autouse=True)
def offline(monkeypatch, caplog):
    # Windows constructs asyncio's internal socketpair via loopback connect.
    # Build the real event loop before forbidding all network connections.
    loop = asyncio.new_event_loop()
    def run(coro):
        with asyncio.Runner(loop_factory=lambda: loop) as runner:
            return runner.run(coro)
    monkeypatch.setattr(asyncio, "run", run)
    def blocked(*args, **kwargs):
        pytest.fail("Real network access is forbidden")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(settings, "HTTP_RETRIES", 2)
    monkeypatch.setattr(settings, "HTTP_BACKOFF", 0)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "PRIVATE_KEY")
    monkeypatch.setattr(logging.getLogger("app.llm.openai_text"), "disabled", False)
    caplog.set_level(logging.INFO, logger="app.llm.openai_text")
    yield
    if not loop.is_closed():
        loop.close()


def completed(**extra):
    return {"status": "completed", "output": [{"type": "message", "role": "assistant",
        "status": "completed", "content": [{"type": "output_text", "text": '{"ok":true}'}]}], **extra}


def install(monkeypatch, *responses):
    original = httpx.AsyncClient
    requests, clients = [], []
    def respond(request):
        requests.append(request)
        assert len(requests) <= len(responses), "Unexpected extra POST"
        response = responses[len(requests) - 1]
        if isinstance(response, Exception):
            raise response
        return response
    def client(**kwargs):
        result = original(**kwargs, transport=httpx.MockTransport(respond), trust_env=False)
        clients.append(result)
        return result
    monkeypatch.setattr(httpx, "AsyncClient", client)
    return requests, clients


def call(**kwargs):
    return asyncio.run(chat(MESSAGES, "configured-model", **kwargs))


def receipts(caplog):
    result = [r for r in caplog.records if r.name == "app.llm.openai_text"
              and getattr(r, "event", None) == "finished"]
    assert "PRIVATE" not in caplog.text
    return result


def wire(requests):
    assert all(r.method == "POST" and r.url.path.endswith("/responses") for r in requests)
    return [json.loads(r.content) for r in requests]


@pytest.mark.parametrize("structured", [False, True])
def test_successful_plain_and_strict_wire_contract(monkeypatch, caplog, structured):
    usage = {"input_tokens": 11, "output_tokens": 8, "total_tokens": 19}
    requests, clients = install(monkeypatch, httpx.Response(200, json=completed(usage=usage)))
    kwargs = {"response_format": FORMAT} if structured else {}
    assert call(**kwargs) == ('{"ok":true}', usage)
    payload, = wire(requests)
    assert payload["model"] == "configured-model" and payload["input"] == MESSAGES
    if structured:
        assert payload["text"]["format"] == FORMAT
    else:
        assert "text" not in payload
    assert 0 < payload["max_output_tokens"] <= MAX_OUTPUT_TOKENS_CAP
    assert receipts(caplog)[0].outcome == "success"
    assert all(c.is_closed for c in clients)


@pytest.mark.parametrize("attempt", [1, 2])
@pytest.mark.parametrize("body,reason", [
    ({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
      "output_text": "PRIVATE_PARTIAL"}, ModelResponseFailureReason.INCOMPLETE_MAX_OUTPUT_TOKENS),
    ({"status": "incomplete", "incomplete_details": {"reason": "content_filter"},
      "output_text": "PRIVATE_PARTIAL"}, ModelResponseFailureReason.INCOMPLETE_CONTENT_FILTER),
    (completed(output_text="PRIVATE_SHORTCUT", output=[{"type": "message", "role": "assistant",
      "content": [{"type": "refusal", "refusal": "PRIVATE_REFUSAL"}]}]), ModelResponseFailureReason.REFUSAL),
    (completed(output=None), ModelResponseFailureReason.INVALID_ENVELOPE),
    ({"output_text": "PRIVATE_WITHOUT_STATUS"}, ModelResponseFailureReason.INVALID_ENVELOPE),
    (completed(output=[{"type": "message", "role": "assistant", "status": "incomplete",
      "content": [{"type": "output_text", "text": "PRIVATE_PARTIAL"}]}]), ModelResponseFailureReason.INVALID_ENVELOPE),
    ([], ModelResponseFailureReason.INVALID_ENVELOPE),
])
def test_every_attempt_rejects_incomplete_refusal_and_invalid_envelope(monkeypatch, caplog, attempt, body, reason):
    responses = [httpx.Response(503, json={})] * (attempt - 1) + [httpx.Response(200, json=body)]
    requests, clients = install(monkeypatch, *responses)
    with pytest.raises(ModelResponseError) as caught:
        call(response_format=FORMAT)
    assert caught.value.reason is reason
    assert len(requests) == attempt
    assert all(p["text"]["format"] == FORMAT for p in wire(requests))
    assert receipts(caplog)[-1].outcome == "rejected"
    assert len(receipts(caplog)) == attempt and all(c.is_closed for c in clients)


@pytest.mark.parametrize("param", ["text", "text.format", "text.format.schema"])
@pytest.mark.parametrize("code", ["unsupported_value", "invalid_request_error"])
def test_schema_400_never_drops_format(monkeypatch, caplog, param, code):
    requests, _ = install(monkeypatch, httpx.Response(400, json={"error": {
        "param": param, "code": code, "message": "PRIVATE_SCHEMA"}}))
    with pytest.raises(httpx.HTTPStatusError):
        call(response_format=FORMAT)
    assert len(requests) == 1 and wire(requests)[0]["text"]["format"] == FORMAT
    assert receipts(caplog)[0].outcome == "http_error"


@pytest.mark.parametrize("retries,expected", [(0, 1), (1, 2), (2, 3), (100, 3), (-1, 1)])
def test_each_post_and_total_send_budget_are_bounded(monkeypatch, caplog, retries, expected):
    requests, _ = install(monkeypatch, *[httpx.Response(503, json={}) for _ in range(expected)])
    monkeypatch.setattr(settings, "HTTP_RETRIES", retries)
    with pytest.raises(httpx.HTTPStatusError):
        call(max_output_tokens=999999, response_format=FORMAT)
    payloads = wire(requests)
    assert len(payloads) == expected
    assert all(p == payloads[0] for p in payloads)
    assert all(p["max_output_tokens"] == MAX_OUTPUT_TOKENS_CAP for p in payloads)
    assert sum(p["max_output_tokens"] for p in payloads) <= 3 * MAX_OUTPUT_TOKENS_CAP
    assert len(receipts(caplog)) == expected


@pytest.mark.parametrize("retries,expected", [(0, 1), (1, 2), (100, 3)])
def test_temperature_compatibility_consumes_the_same_budget(monkeypatch, caplog, retries, expected):
    replies = [httpx.Response(400, json={"error": {"param": "temperature", "code": "unsupported_value"}})]
    replies += [httpx.Response(503, json={}) for _ in range(expected - 1)]
    requests, _ = install(monkeypatch, *replies)
    monkeypatch.setattr(settings, "HTTP_RETRIES", retries)
    with pytest.raises(httpx.HTTPStatusError):
        call(temperature=.2, max_output_tokens=999999, response_format=FORMAT)
    payloads = wire(requests)
    assert len(payloads) == len(receipts(caplog)) == expected
    assert "temperature" in payloads[0]
    assert all("temperature" not in p for p in payloads[1:])
    assert all(p["max_output_tokens"] == MAX_OUTPUT_TOKENS_CAP and p["text"]["format"] == FORMAT for p in payloads)


def test_two_responses_preserve_separate_usage_receipts(monkeypatch, caplog):
    first = {"input_tokens": 11, "output_tokens": 20, "total_tokens": 31}
    second = {"input_tokens": 13, "output_tokens": 7, "total_tokens": 20}
    requests, _ = install(monkeypatch,
        httpx.Response(503, json={"usage": first}, headers={"x-request-id": "req_first"}),
        httpx.Response(200, json=completed(usage=second, id="resp_second"), headers={"x-request-id": "req_second"}))
    assert call(response_format=FORMAT)[1] == second
    records = receipts(caplog)
    assert [r.input_tokens for r in records] == [11, 13]
    assert [r.output_tokens for r in records] == [20, 7]
    assert [r.total_tokens for r in records] == [31, 20]
    assert [r.x_request_id for r in records] == ["req_first", "req_second"]
    assert len({r.provider_call_id for r in records}) == len(requests) == 2
    assert records[0].schema_fingerprint == records[1].schema_fingerprint
    assert all(r.billing_outcome == "unknown" for r in records)


@pytest.mark.parametrize("extra,state,scalar", [({}, "missing", "missing"),
    ({"usage": None}, "null", "missing"), ({"usage": {}}, "present", "missing"),
    ({"usage": {"output_tokens": 0}}, "present", "reported"),
    ({"usage": False}, "invalid", "missing")])
def test_missing_usage_is_never_reported_as_zero(monkeypatch, caplog, extra, state, scalar):
    install(monkeypatch, httpx.Response(200, json=completed(**extra)))
    result = call()
    record, = receipts(caplog)
    assert record.usage_state == state and record.output_tokens_state == scalar
    assert hasattr(record, "output_tokens") == (scalar == "reported")
    assert record.billing_outcome == "unknown"
    assert result[1] == (extra.get("usage") if isinstance(extra.get("usage"), dict) else {})


@pytest.mark.parametrize("error", [httpx.ReadTimeout("PRIVATE_TIMEOUT"),
    httpx.WriteError("PRIVATE_WRITE"), httpx.ConnectError("PRIVATE_CONNECT"),
    httpx.RemoteProtocolError("PRIVATE_LOST_RESPONSE"), TimeoutError("PRIVATE_TIMEOUT")])
@pytest.mark.parametrize("attempt", [1, 2])
def test_unknown_outcome_never_reposts(monkeypatch, caplog, error, attempt):
    replies = [httpx.Response(503, json={})] * (attempt - 1) + [error]
    requests, clients = install(monkeypatch, *replies)
    with pytest.raises(type(error)):
        call(response_format=FORMAT)
    record = receipts(caplog)[-1]
    assert len(wire(requests)) == attempt and record.outcome_unknown
    assert record.usage_state == "unavailable" and record.billing_outcome == "unknown"
    assert not hasattr(record, "output_tokens") and all(c.is_closed for c in clients)


def test_http_408_does_not_repeat_unknown_outcome(monkeypatch, caplog):
    requests, _ = install(monkeypatch, httpx.Response(408, json={}))
    with pytest.raises(httpx.HTTPStatusError):
        call()
    assert len(requests) == 1 and receipts(caplog)[0].outcome_unknown


def test_invalid_json_is_terminal(monkeypatch, caplog):
    requests, _ = install(monkeypatch, httpx.Response(200, content=b"PRIVATE_INVALID_JSON"))
    with pytest.raises(ModelResponseError) as caught:
        call()
    assert caught.value.reason is ModelResponseFailureReason.INVALID_ENVELOPE
    assert len(requests) == 1 and receipts(caplog)[0].outcome == "rejected"

@pytest.mark.parametrize("empty_zero", [False, True])
def test_token_exhaustion_cannot_expand_capped_payload(monkeypatch, caplog, empty_zero):
    requests = []
    original = httpx.AsyncClient
    body = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
            "output": [], "usage": {"input_tokens": 11,
                "output_tokens": 0 if empty_zero else MAX_OUTPUT_TOKENS_CAP,
                "output_tokens_details": {"reasoning_tokens": 0 if empty_zero else MAX_OUTPUT_TOKENS_CAP}}}
    def respond(request):
        requests.append(request)
        payload = json.loads(request.content)
        # Also fails at the exact old multiplier bug if a second POST is attempted.
        assert payload["max_output_tokens"] <= MAX_OUTPUT_TOKENS_CAP
        assert payload["text"]["format"] == FORMAT
        return httpx.Response(200, json=body)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        **kw, transport=httpx.MockTransport(respond), trust_env=False))
    with pytest.raises(ModelResponseError) as caught:
        call(max_output_tokens=999999, response_format=FORMAT)
    expected = (ModelResponseFailureReason.INCOMPLETE_EMPTY_MAX_OUTPUT_TOKENS if empty_zero
                else ModelResponseFailureReason.INCOMPLETE_MAX_OUTPUT_TOKENS)
    assert caught.value.reason is expected
    assert len(requests) == 1 and wire(requests)[0]["max_output_tokens"] == MAX_OUTPUT_TOKENS_CAP
    record, = receipts(caplog)
    assert record.input_tokens == 11 and record.billing_outcome == "unknown"
