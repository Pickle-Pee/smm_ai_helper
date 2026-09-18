"""Exercise the real project HTTP transport through the production module adapter."""
import asyncio
import json

import httpx
import pytest

from app.config import settings
from app.module_execution import ModuleExecutorDispatcher
from app.module_execution.executors import ExecutorOutputError
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.worker import transient
from tests.test_module_executors import analyzer, request as module_request
from tests.test_production_graph_worker import queue


def install_transport(monkeypatch, responder):
    original = httpx.AsyncClient
    clients = []
    def client(**kwargs):
        result = original(**kwargs, transport=httpx.MockTransport(responder))
        clients.append(result)
        return result
    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://provider.test/v1")
    monkeypatch.setattr(settings, "HTTP_RETRIES", 8)  # Graph explicitly opts out.
    return clients


def test_adapter_preserves_schema_bound_and_raw_text(monkeypatch):
    seen = []
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"output_text": '{"malformed":true}', "usage": {"total_tokens": 12}})
    clients = install_transport(monkeypatch, respond)
    schema = {"type": "object", "properties": {}, "additionalProperties": False, "required": []}
    raw = asyncio.run(production_model_call(instruction="Strict JSON; no hidden reasoning", text="input", response_schema=schema))
    assert raw == '{"malformed":true}' and len(seen) == 1
    assert seen[0]["input"] == [{"role": "system", "content": "Strict JSON; no hidden reasoning"},
                                {"role": "user", "content": "input"}]
    assert seen[0]["text"]["format"] == {"type": "json_schema", "name": "module_output", "strict": True, "schema": schema}
    assert seen[0]["max_output_tokens"] == 4000
    assert all(c.is_closed for c in clients)


@pytest.mark.parametrize("mode,retryable", [
    ("timeout", True), ("network", True), (408, True), (429, True), (500, True), (502, True),
    (503, True), (504, True), (400, False), (401, False), (403, False),
    ("json", False), ("incomplete", False), ("refusal", False),
])
def test_one_request_no_fallback_no_expansion_and_safe_errors(monkeypatch, caplog, mode, retryable):
    calls = []
    def respond(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("SECRET", request=request)
        if mode == "network":
            raise httpx.ConnectError("SECRET", request=request)
        if isinstance(mode, int):
            return httpx.Response(mode, json={"error": {"param": "text.format", "code": "unsupported_value", "message": "SECRET"}})
        if mode == "json":
            return httpx.Response(200, text="SECRET not json")
        if mode == "incomplete":
            return httpx.Response(200, json={"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                                             "output_text": "{}"})
        return httpx.Response(200, json={"output": [{"type": "message", "role": "assistant",
                                                    "content": [{"type": "refusal", "refusal": "SECRET"}]}]})
    clients = install_transport(monkeypatch, respond)
    with pytest.raises(Exception) as caught:
        asyncio.run(production_model_call(instruction="SECRET", text="SECRET", response_schema={}))
    assert transient(caught.value) is retryable
    assert len(calls) == 1 and all(c.is_closed for c in clients)
    assert "SECRET" not in caplog.text


def test_empty_or_malformed_text_reaches_strict_executor_without_retry(monkeypatch):
    # Same production adapter + real executor parser; no repair or fake success.
    from app.module_registry import ModuleId
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"output_text": "not JSON SECRET"})
    install_transport(monkeypatch, respond)
    runtime = build_production_graph_runtime(queue=queue(), analyzer=analyzer())
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ModuleExecutorDispatcher(runtime.executors).dispatch(
            runtime.metadata.get(ModuleId.POSITIONING).execution_binding, module_request(ModuleId.POSITIONING)))
    assert len(calls) == 1


def test_cancel_closes_owned_transport_without_retry(monkeypatch):
    async def exercise():
        entered = asyncio.Event()
        async def respond(request):
            entered.set()
            await asyncio.Event().wait()
        clients = install_transport(monkeypatch, respond)
        task = asyncio.create_task(production_model_call(instruction="x", text="x", response_schema={}))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(clients) == 1 and clients[0].is_closed
    asyncio.run(exercise())
