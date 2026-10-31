"""Production wire projection, original validation, gates and rollout switch."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import logging

import pytest

from app.config import settings
from app.module_execution import UpstreamExecutionResult
from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors import PositioningExecutor, ExecutorOutputError, build_module_executor_registry
from app.module_execution.executors import common, positioning as positioning_module
from app.module_execution.executors.provider_schema import (
    SchemaProjectionError, collapse_single_support_anyof, schema_measurement,
)
from app.module_registry import ModuleId, ModuleRegistry
from app.module_execution.executors.positioning_observation_schema import positioning_observation_schema
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.service import evaluate_result
from app.orchestration_runtime.worker import transient
from tools.positioning_diagnostics import capture_request, metadata
from tests.positioning_provider import PositioningProvider
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import FakeModel, analyzer, dispatch, request
from tests.test_positioning_seed_contract import seed_request
from tests.test_production_graph_worker import queue
from tests.test_strategy_intelligence import IntelligenceModel, valid_request


@pytest.mark.parametrize("job,alternative", [(False, False), (False, True), (True, False), (True, True)])
@pytest.mark.parametrize("parents", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_real_adapter_projects_only_wire_schema_and_passes_original_validation_and_gates(
        monkeypatch, caplog, job, alternative, parents, enabled):
    invocation = replace(seed_request(job, alternative), execution_id="a" * 32)
    if parents:
        predecessor = dispatch(request(ModuleId.COMPETITOR_ANALYSIS, identity="b" * 32))
        invocation = replace(invocation, upstream_results=(UpstreamExecutionResult(
            producer_node_id="competitor_analysis", result=predecessor),))
    monkeypatch.setattr(settings, "DEFAULT_TEXT_MODEL_HARD", "gpt-5-mini")
    baseline = asyncio.run(capture_request(invocation, model="gpt-5-mini"))
    original = deepcopy(baseline.arguments["response_schema"])
    validators = []
    factory = common.Draft202012Validator
    def track(schema):
        validators.append(schema)
        return factory(schema)
    monkeypatch.setattr(common, "Draft202012Validator", track)
    monkeypatch.setattr(common.log, "disabled", False)
    provider = PositioningProvider()
    install_transport(monkeypatch, provider)
    with caplog.at_level(logging.INFO, logger=common.log.name):
        result = asyncio.run(PositioningExecutor(model_call=production_model_call,
            provider_schema_projection=enabled).execute(invocation))
    assert validators == [original]
    projected = positioning_observation_schema(collapse_single_support_anyof(original) if enabled else original)
    expected_wire = deepcopy(baseline.payload)
    expected_wire["text"]["format"]["schema"] = projected
    assert provider.calls == [expected_wire]
    assert metadata(baseline)["baseline_mode"] == "original_unprojected"
    quality = evaluate_result(invocation.execution_id, result, invocation.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    assert len(result.normalized_result.claims) == 16
    assert all(claim.evidence_ids for claim in result.normalized_result.claims)
    record = next(r for r in caplog.records if r.getMessage().startswith("POSITIONING provider schema "))
    assert record.schema_projection_enabled is enabled
    assert record.schema_projection_applied is (enabled and not parents)
    assert record.schema_projection_nodes == (0 if not enabled or parents else 2 if job and alternative else 4)
    assert record.validation_schema_sha256 == schema_measurement(original)["sha256"]
    assert record.provider_schema_sha256 == schema_measurement(projected)["sha256"]
    assert record.validation_schema_bytes == schema_measurement(original)["bytes"]
    assert record.provider_schema_bytes == schema_measurement(projected)["bytes"]
    rendered = record.getMessage()
    assert "Supplied" not in rendered and "evd_" not in rendered and "clm_" not in rendered


@pytest.mark.parametrize("enabled", [False, True])
def test_config_gate_is_injected_into_production_registry(monkeypatch, enabled):
    monkeypatch.setattr(settings, "POSITIONING_SCHEMA_PROJECTION_ENABLED", enabled)
    provider = PositioningProvider()
    install_transport(monkeypatch, provider)
    runtime = build_production_graph_runtime(queue=queue(), analyzer=analyzer())
    invocation = seed_request(True, False)
    baseline = asyncio.run(capture_request(invocation, model=settings.DEFAULT_TEXT_MODEL_HARD))
    asyncio.run(runtime.executors.resolve("positioning.v1").execute(invocation))
    assert provider.calls[0]["text"]["format"]["schema"] == positioning_observation_schema(
        collapse_single_support_anyof(baseline.arguments["response_schema"]) if enabled else baseline.arguments["response_schema"])
    # A globally enabled production configuration must never project diagnostic baseline.
    assert asyncio.run(capture_request(invocation, model=settings.DEFAULT_TEXT_MODEL_HARD)).payload == baseline.payload
    from app.config import Settings
    assert Settings.model_fields["POSITIONING_SCHEMA_PROJECTION_ENABLED"].default is False


@pytest.mark.parametrize("mutation,stage", [
    (lambda p,d: p["outputs"][0].update(evidence_ids=["evd_unknown"]), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(parent_claim_ids=["clm_unknown"]), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(evidence_ids=[], parent_claim_ids=[]), "schema_invalid"),
    (lambda p,d: next(s for s in p["outputs"] if s["output_name"] == "differentiation").update(kind="OBSERVATION"), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(output_name="unknown"), "schema_invalid"),
    (lambda p,d: p["outputs"].pop(), "output_coverage_invalid"),
    (lambda p,d: p["outputs"][0]["evidence_ids"].append(p["outputs"][0]["evidence_ids"][0]), "support_identity_invalid"),
    (lambda p,d: next(s for s in p["outputs"] if s["output_name"] == "RTB").update(evidence_ids=[
        next(e["evidence_id"] for e in d["local_evidence"] if e["input_key"] == "target_or_target_hypothesis")]), "statement_semantics_invalid"),
    (lambda p,d: p["outputs"][0].update(confidence=float("nan")), "json_invalid"),
    (lambda p,d: p["outputs"][0].update(confidence=float("inf")), "json_invalid"),
    (lambda p,d: p["outputs"][0].update(text=""), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(text="x" * 4001), "schema_invalid"),
])
def test_projection_keeps_fail_closed_output_pipeline(monkeypatch, mutation, stage):
    provider = PositioningProvider(mutation)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=production_model_call,
            provider_schema_projection=True).execute(seed_request(True, False)))
    assert caught.value.stage.value == stage and not transient(caught.value)
    assert len(provider.calls) == 1


def test_provider_cannot_mutate_original_validation_schema(monkeypatch):
    validators = []
    factory = common.Draft202012Validator
    def track(schema):
        validators.append(schema)
        return factory(schema)
    monkeypatch.setattr(common, "Draft202012Validator", track)
    fake = FakeModel(lambda p,d: p["outputs"][0].update(evidence_ids=["evd_unknown"]))
    async def mutable_capability(**kwargs):
        raw = await fake(**kwargs)
        kwargs["response_schema"].clear()  # Deliberately malicious injected capability.
        return raw
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=mutable_capability,
            provider_schema_projection=True).execute(seed_request(True, False)))
    assert caught.value.stage.value == "schema_invalid"
    assert validators[0]["$defs"] and not fake.calls[0]["response_schema"]


def test_failed_equivalence_proof_prevents_model_call_and_retry(monkeypatch, caplog):
    original_builder = common.support_response_schema
    def unsafe(*args, **kwargs):
        schema = original_builder(*args, **kwargs)
        definition = next(v for v in schema["$defs"].values() if "anyOf" in v)
        definition["anyOf"][0]["properties"]["text"]["maxLength"] = 99
        return schema
    monkeypatch.setattr(common, "support_response_schema", unsafe)
    monkeypatch.setattr(common.log, "disabled", False)
    fake = FakeModel()
    with pytest.raises(SchemaProjectionError) as caught:
        asyncio.run(PositioningExecutor(model_call=fake, provider_schema_projection=True).execute(seed_request(True, False)))
    assert not fake.calls and not transient(caught.value)
    assert str(caught.value) == "single_support_anyof_not_equivalent"
    assert "evd_" not in caplog.text and "properties" not in caplog.text


def test_disabled_gate_never_calls_projection(monkeypatch):
    monkeypatch.setattr(positioning_module, "collapse_single_support_anyof", lambda *_: pytest.fail("projection invoked"))
    result = asyncio.run(PositioningExecutor(model_call=FakeModel()).execute(seed_request(True, False)))
    assert result.normalized_result.claims


@pytest.mark.parametrize("module", [ModuleId.COMPETITOR_ANALYSIS, ModuleId.CREATOR,
    ModuleId.MARKET_ANALYSIS, ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
def test_other_modules_preserve_exact_model_arguments_when_flag_changes(module):
    invocation = request(module) if module in (ModuleId.COMPETITOR_ANALYSIS, ModuleId.CREATOR) else valid_request(module)
    calls = []
    for enabled in (False, True):
        fake = IntelligenceModel(use_parents=True)
        registry = build_module_executor_registry(model_call=fake, analyzer=analyzer(), market_analyzer=analyzer(),
            registry_version="1.3.0", positioning_schema_projection=enabled)
        binding = ModuleRegistry.load("1.3.0").get(module).execution_binding
        asyncio.run(registry.resolve(binding.executor_key).execute(invocation))
        calls.append(fake.calls)
    assert calls[0] == calls[1]
