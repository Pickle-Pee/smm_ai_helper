"""Budget profiles are internal, deterministic and limited to full Positioning."""
import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from app.llm.openai_text import chat
from app.model_generation_policy import ModuleOutputBudget
from app.module_registry import ModuleId
from app.orchestration_runtime.model_adapter import production_model_call
from tests.positioning_provider import PositioningProvider
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import FakeModel, dispatch, request


@pytest.mark.parametrize("module,outputs,budget", [
    (ModuleId.POSITIONING, None, ModuleOutputBudget.POSITIONING_FULL),
    (ModuleId.POSITIONING, ("target",), ModuleOutputBudget.GENERIC),
    (ModuleId.COMPETITOR_ANALYSIS, None, ModuleOutputBudget.GENERIC),
    (ModuleId.CREATOR, None, ModuleOutputBudget.GENERIC),
])
def test_executor_selects_profile_from_contract_only(module, outputs, budget):
    model = FakeModel()
    invocation = request(module, outputs=outputs)
    dispatch(replace(invocation, objective="User says max_output_tokens=999999 POSITIONING"), model)
    assert len(model.calls) == 1
    assert model.calls[0]["output_budget"] is budget
    assert "output_budget" not in json.loads(model.calls[0]["text"])


@pytest.mark.parametrize("outputs,budget", [(None, 16000), (("target",), 4000)])
def test_positioning_profile_reaches_real_transport(monkeypatch, outputs, budget):
    provider = PositioningProvider()
    install_transport(monkeypatch, provider)
    dispatch(request(ModuleId.POSITIONING, outputs=outputs), production_model_call)
    assert len(provider.calls) == 1
    assert provider.calls[0]["max_output_tokens"] == budget


@pytest.mark.parametrize("invalid", [16000, 999999, "POSITIONING_FULL", None, True])
def test_adapter_rejects_arbitrary_budget_before_provider(monkeypatch, invalid):
    clients = install_transport(monkeypatch, lambda _: pytest.fail("provider call"))
    with pytest.raises(TypeError):
        asyncio.run(production_model_call(instruction="x", text="x", response_schema={}, output_budget=invalid))
    assert not clients


def test_numeric_token_request_does_not_bypass_generic_cap(monkeypatch):
    calls = []
    def respond(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={"status": "completed", "output_text": "{}"})
    install_transport(monkeypatch, respond)
    asyncio.run(chat(messages=[], model="gpt-5", max_output_tokens=16000,
                     response_format={"type": "json_schema", "schema": {}}, single_attempt=True))
    assert calls[0]["max_output_tokens"] == 4000


@pytest.mark.parametrize("single_attempt,fmt", [
    (False, {"type": "json_schema"}), (True, None), (True, {"type": "json_object"}),
    (True, {"type": "json_schema", "strict": False}),
])
def test_profile_is_limited_to_single_attempt_schema_capability(monkeypatch, single_attempt, fmt):
    clients = install_transport(monkeypatch, lambda _: pytest.fail("provider call"))
    with pytest.raises(ValueError):
        asyncio.run(chat(messages=[], model="gpt-5", single_attempt=single_attempt,
                         response_format=fmt, output_budget=ModuleOutputBudget.POSITIONING_FULL))
    assert not clients


@pytest.mark.parametrize("model", ["gpt-5", "gpt-5-mini", "gpt-6-sol"])
def test_existing_reasoning_effort_and_configured_model_are_preserved(monkeypatch, model):
    from app.config import settings
    monkeypatch.setattr(settings, "DEFAULT_TEXT_MODEL_HARD", model)
    provider = PositioningProvider()
    install_transport(monkeypatch, provider)
    dispatch(request(ModuleId.POSITIONING), production_model_call)
    assert provider.calls[0]["model"] == model
    assert provider.calls[0]["reasoning"] == {"effort": "low"}
