"""Offline rollout wiring: one production registry, independent POSITIONING flags."""
import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.config import Settings, settings
from app.marketing_copilot.production import build_production_copilot_api
from app.module_execution.executors import PositioningExecutor, build_module_executor_registry
from app.module_execution.executors.product_support import WIRE_VERSION
from app.module_registry import ModuleId
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.orchestration_runtime.serialization import result_to_json
from tests.test_module_executors import FakeModel, analyzer, request
from tests.test_positioning_product_wire import ProductModel, invocation
from tests.test_production_graph_worker import queue
from tests.test_strategy_intelligence import IntelligenceModel, valid_request


def test_setting_defaults_off_and_accepts_environment_override(monkeypatch):
    name = "POSITIONING_PRODUCT_SUPPORT_WIRE_ENABLED"
    assert Settings.model_fields[name].default is False
    monkeypatch.delenv(name, raising=False)
    config = dict(DATABASE_URL="postgresql+asyncpg://offline/offline",
                  TELEGRAM_BOT_TOKEN="offline", OPENAI_API_KEY="offline")
    assert getattr(Settings(_env_file=None, **config), name) is False
    for value, expected in (("true", True), ("false", False)):
        monkeypatch.setenv(name, value)
        assert getattr(Settings(_env_file=None, **config), name) is expected


@pytest.mark.parametrize("projection", [False, True])
@pytest.mark.parametrize("wire", [False, True])
def test_registry_flags_are_independent_and_select_provider_contract(projection, wire):
    model = ProductModel() if wire else FakeModel()
    registry = build_module_executor_registry(model_call=model, analyzer=analyzer(),
        registry_version="1.3.0", positioning_schema_projection=projection,
        positioning_product_support_wire=wire)
    executor = registry.resolve("positioning.v1")
    assert executor._provider_schema_projection is projection
    assert executor._product_support_wire is wire
    result = asyncio.run(executor.execute(invocation(True, True)))
    schema = model.calls[0]["response_schema"]
    assert ("wire_contract_version" in schema["properties"]) is wire
    assert ("AllowedProductSupportId" in schema["$defs"]) is wire
    if wire:
        assert schema["properties"]["wire_contract_version"]["enum"] == [WIRE_VERSION]
        assert model.payload["wire_contract_version"] == WIRE_VERSION
    assert result.schema_version == "positioning.payload.v1"
    assert "wire_contract_version" not in result.payload
    assert all("product_support_id" not in item for item in result.payload["outputs"])


@pytest.mark.parametrize("projection", [False, True])
@pytest.mark.parametrize("wire", [False, True])
def test_production_graph_and_api_share_flagged_registry(monkeypatch, projection, wire):
    monkeypatch.setattr(settings, "POSITIONING_SCHEMA_PROJECTION_ENABLED", projection)
    monkeypatch.setattr(settings, "POSITIONING_PRODUCT_SUPPORT_WIRE_ENABLED", wire)
    monkeypatch.setattr(httpx, "AsyncClient", Mock(side_effect=AssertionError("network forbidden")))
    sessions = Mock(side_effect=AssertionError("database forbidden"))
    model = ProductModel() if wire else FakeModel()
    runtime = build_production_graph_runtime(queue=queue(), sessions=sessions,
        model_call=model, analyzer=analyzer())
    api = build_production_copilot_api(queue=queue(), sessions=sessions,
        module_model=model, analyzer=analyzer(), intent_model=AsyncMock(),
        owned_analyzer=analyzer(), extractor=AsyncMock())
    shared = api.copilot.graph_service.executors
    assert api.copilot.dispatcher._registry is shared
    assert runtime.service.executors is runtime.executors
    for registry in (runtime.executors, shared):
        executor = registry.resolve("positioning.v1")
        assert executor._provider_schema_projection is projection
        assert executor._product_support_wire is wire
        result = asyncio.run(executor.execute(invocation(False, False)))
        assert ("wire_contract_version" in model.calls[-1]["response_schema"]["properties"]) is wire
        assert result.schema_version == "positioning.payload.v1"
    assert api.copilot.metadata.version == runtime.metadata.version == "1.3.0"
    assert len(shared.executor_keys) == len(runtime.executors.executor_keys) == 6
    sessions.assert_not_called()


@pytest.mark.parametrize("projection", [False, True])
def test_default_and_explicit_off_preserve_v1_schema_prompt_and_result(projection):
    req = invocation(False, True)
    baseline_model = FakeModel()
    baseline = asyncio.run(PositioningExecutor(model_call=baseline_model,
        provider_schema_projection=projection).execute(req))
    for override in ({}, {"positioning_product_support_wire": False}):
        model = FakeModel()
        registry = build_module_executor_registry(model_call=model, analyzer=analyzer(),
            registry_version="1.3.0", positioning_schema_projection=projection, **override)
        result = asyncio.run(registry.resolve("positioning.v1").execute(req))
        assert model.calls == baseline_model.calls
        assert result_to_json(result) == result_to_json(baseline)
        assert "wire_contract_version" not in model.calls[0]["response_schema"]["properties"]


@pytest.mark.parametrize("module", [ModuleId.COMPETITOR_ANALYSIS, ModuleId.CREATOR,
    ModuleId.MARKET_ANALYSIS, ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
def test_wire_flag_does_not_change_other_modules(module):
    req = (request(module) if module in {ModuleId.COMPETITOR_ANALYSIS, ModuleId.CREATOR}
           else valid_request(module))
    runs = []
    for wire in (False, True):
        model, site = IntelligenceModel(use_parents=True), analyzer()
        registry = build_module_executor_registry(model_call=model, analyzer=site,
            market_analyzer=site, registry_version="1.3.0", positioning_product_support_wire=wire)
        executor = next(registry.resolve(key) for key in registry.executor_keys
                        if registry.resolve(key).module_id is module)
        result = asyncio.run(executor.execute(req))
        runs.append((model.calls, result_to_json(result), site.analyze.call_args_list))
    assert runs[0] == runs[1]
