"""Correlation/redaction at real adapter/HTTP boundaries; no live provider calls."""
import asyncio
import hashlib
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import settings
from app.llm.openai_text import ModelResponseError, chat
from app.llm.telemetry import correlation_fields, graph_call_context
from app.module_execution import ModuleExecutorRegistry
from app.module_execution.executors.common import ExecutorOutputError
from app.module_registry import ModuleId
from app.orchestration_runtime.contracts import GraphWorkItem
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.test_graph_model_adapter import install_transport
from tests.test_model_response_failures import empty_incomplete

SECRET = "SENTINEL_PRIVATE_CONTENT"
SCHEMA = {"type": "object", "description": SECRET, "properties": {}}


@pytest.fixture(autouse=True)
def capture_telemetry(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="app.llm.openai_text")
    monkeypatch.setattr(logging.getLogger("app.llm.openai_text"), "disabled", False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-" + SECRET)


def events(caplog, event="finished"):
    return [r for r in caplog.records if r.name == "app.llm.openai_text"
            and getattr(r, "event", None) == event]


def assert_redacted(caplog):
    captured = caplog.text + str([r.__dict__ for r in caplog.records])
    assert SECRET not in captured
    for value in ("Authorization", "Bearer", "claim_token", "output_text", "description"):
        assert value not in captured
    assert all(r.exc_info is None for r in events(caplog))


def identity(attempt=1, job="job_one"):
    item = GraphWorkItem(job, "run_one", 1, "node_one", SECRET + str(attempt), attempt)
    request = SimpleNamespace(module_id=ModuleId.VIRTUAL_CMO, execution_id=job)
    return item, request


async def call():
    return await production_model_call(instruction=SECRET, text=SECRET, response_schema=SCHEMA)


@pytest.mark.parametrize("mode,outcome", [("success", "success"), ("empty", "rejected"),
    ("http", "http_error"), ("transport", "transport_error"), ("timeout", "timeout")])
def test_outcomes_correlate_and_redact(monkeypatch, caplog, mode, outcome):
    requests = []
    def respond(request):
        requests.append(request)
        if mode in ("transport", "timeout"):
            cls = httpx.ConnectError if mode == "transport" else httpx.ReadTimeout
            raise cls(SECRET, request=request)
        body = empty_incomplete() if mode == "empty" else {
            "status": "completed", "output_text": SECRET,
            "usage": {"input_tokens": 0, "output_tokens": None, "total_tokens": 0}}
        body.update(id="resp_test", error=SECRET)
        return httpx.Response(503 if mode == "http" else 200, json=body,
                              headers={"x-request-id": "req_test", "Authorization": SECRET})
    clients = install_transport(monkeypatch, respond)
    item, request = identity()
    async def exercise():
        with graph_call_context(item, request, None):
            if mode == "success":
                assert await call() == SECRET
            else:
                with pytest.raises((httpx.HTTPError, ModelResponseError)):
                    await call()
        assert correlation_fields() == {"correlation_state": "unbound"}
    asyncio.run(exercise())
    assert len(requests) == 1 and all(c.is_closed for c in clients)
    started, finished = events(caplog, "started"), events(caplog)
    assert len(started) == len(finished) == 1
    record = finished[0]
    assert started[0].provider_call_id == record.provider_call_id
    assert record.telemetry_version == "llm_provider_request.v1"
    assert record.outcome == outcome and record.duration_ms >= 0
    assert record.job_id == record.module_execution_id == item.job_id
    assert record.run_id == item.run_id and record.node_id == item.node_id
    assert record.module_id == ModuleId.VIRTUAL_CMO.value and record.graph_attempt == 1
    assert record.graph_attempt_id == hashlib.sha256(item.claim_token.encode()).hexdigest()
    assert record.model == settings.DEFAULT_TEXT_MODEL_HARD and record.max_output_tokens == 4000
    assert record.schema_fingerprint == hashlib.sha256(json.dumps(
        SCHEMA, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if mode in ("timeout", "transport"):
        assert record.http_status is None and not record.response_received
        assert record.response_status == record.usage_state == "unavailable"
        assert not hasattr(record, "response_id") and not hasattr(record, "x_request_id")
    else:
        assert record.response_id == "resp_test" and record.x_request_id == "req_test"
        assert record.http_status == (503 if mode == "http" else 200)
        if mode == "empty":
            assert record.reason == "incomplete_empty_max_output_tokens"
            assert record.incomplete_reason == "max_output_tokens"
            assert record.output_tokens == record.reasoning_tokens == 0
    assert_redacted(caplog)


@pytest.mark.parametrize("extra,state", [({}, "missing"), ({"usage": None}, "null"),
    ({"usage": {}}, "present"), ({"usage": SECRET}, "invalid")])
def test_success_usage_container_states(monkeypatch, caplog, extra, state):
    install_transport(monkeypatch, lambda _: httpx.Response(200, json={
        "status": "completed", "output_text": SECRET, **extra}))
    asyncio.run(call())
    assert events(caplog)[0].usage_state == state
    assert not hasattr(events(caplog)[0], "input_tokens")
    assert_redacted(caplog)


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "total_tokens", "reasoning_tokens"])
@pytest.mark.parametrize("value,state", [("absent", "missing"), (None, "null"), (0, "reported"),
    (False, "invalid"), (SECRET, "invalid"), (2 ** 100, "invalid")])
def test_success_usage_scalar_states(monkeypatch, caplog, field, value, state):
    usage = {}
    container = usage.setdefault("output_tokens_details", {}) if field == "reasoning_tokens" else usage
    if value != "absent":
        container[field] = value
    install_transport(monkeypatch, lambda _: httpx.Response(200, json={
        "status": "completed", "output_text": SECRET, "usage": usage}))
    asyncio.run(call())
    record = events(caplog)[0]
    assert getattr(record, field + "_state") == state
    assert hasattr(record, field) == (state == "reported")
    if state == "reported":
        assert getattr(record, field) == 0
    assert_redacted(caplog)


@pytest.mark.parametrize("value", [SECRET, "sk-" + SECRET, "PRIVATE header\tcontent", "x" * 129])
def test_untrusted_provider_labels_are_not_logged(monkeypatch, caplog, value):
    install_transport(monkeypatch, lambda _: httpx.Response(200, json={
        "status": "completed", "output_text": SECRET, "id": value,
        "incomplete_details": {"reason": SECRET}}, headers={"x-request-id": value}))
    asyncio.run(call())
    assert not hasattr(events(caplog)[0], "response_id")
    assert not hasattr(events(caplog)[0], "x_request_id")
    assert events(caplog)[0].incomplete_reason == "other"
    assert_redacted(caplog)


def test_concurrent_attempts_for_same_execution_do_not_share_context(monkeypatch, caplog):
    async def concurrent_only():
        entered = 0
        barrier = asyncio.Event()
        async def respond(request):
            nonlocal entered
            entered += 1
            attempt = correlation_fields().get("graph_attempt", 0)
            if entered >= 2:
                barrier.set()
            await barrier.wait()
            return httpx.Response(200, json={"status": "completed", "output_text": SECRET,
                "id": f"resp_{attempt}"}, headers={"x-request-id": f"req_{attempt}"})
        install_transport(monkeypatch, respond)
        async def execute(attempt):
            item, request = identity(attempt)
            with graph_call_context(item, request, None):
                await call()
            assert correlation_fields()["correlation_state"] == "unbound"
        await asyncio.gather(execute(1), execute(2))
        await call()
    asyncio.run(concurrent_only())
    bound = [r for r in events(caplog) if r.correlation_state == "graph"]
    assert len(bound) == 2 and {r.graph_attempt for r in bound} == {1, 2}
    assert len({r.graph_attempt_id for r in bound}) == 2
    assert len({r.provider_call_id for r in events(caplog)}) == 3
    assert all(r.response_id == f"resp_{r.graph_attempt}" and r.x_request_id == f"req_{r.graph_attempt}"
               and r.job_id == "job_one" for r in bound)
    assert events(caplog)[-1].correlation_state == "unbound"
    assert not hasattr(events(caplog)[-1], "job_id")
    assert_redacted(caplog)


@pytest.mark.parametrize("mode", ["timeout", "cancelled"])
def test_worker_deadline_and_shutdown_cancellation_are_distinct(monkeypatch, caplog, mode):
    async def exercise():
        entered = asyncio.Event()
        async def respond(request):
            entered.set()
            await asyncio.Event().wait()
        clients = install_transport(monkeypatch, respond)
        item, request = identity(2)
        service = SimpleNamespace(lease_seconds=330, executors=ModuleExecutorRegistry(),
            claim=AsyncMock(return_value=item), load_work=AsyncMock(return_value=(object(), request)),
            fail=AsyncMock(), finish=AsyncMock())
        worker = ModuleGraphWorker(service, timeout_seconds=.1 if mode == "timeout" else 300)
        async def dispatch(*_):
            await call()
            raise ExecutorOutputError()
        worker.dispatcher.dispatch = dispatch
        task = asyncio.create_task(worker.once())
        await asyncio.wait_for(entered.wait(), 2)
        if mode == "cancelled":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            service.fail.assert_not_awaited()
        else:
            assert await task
            service.fail.assert_awaited_once_with(item, code="provider_transient", retryable=True)
        service.finish.assert_not_awaited()
        assert all(c.is_closed for c in clients)
        assert correlation_fields()["correlation_state"] == "unbound"
    asyncio.run(exercise())
    record = events(caplog)[0]
    assert record.outcome == mode and record.graph_attempt == 2 and record.job_id == "job_one"
    assert_redacted(caplog)


def test_legacy_fallback_posts_are_each_observed_without_adding_calls(monkeypatch, caplog):
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(400, json={"error": {"param": "temperature", "code": "unsupported_value"}})
        return httpx.Response(200, json={"status": "completed", "output_text": SECRET})
    install_transport(monkeypatch, respond)
    assert asyncio.run(chat([{"role": "user", "content": SECRET}], "configured-model", temperature=.2))[0] == SECRET
    assert len(requests) == len(events(caplog)) == len(events(caplog, "started")) == 2
    assert "temperature" in requests[0] and "temperature" not in requests[1]
    assert len({r.provider_call_id for r in events(caplog)}) == 2
    assert [r.outcome for r in events(caplog)] == ["http_error", "success"]
    assert_redacted(caplog)
