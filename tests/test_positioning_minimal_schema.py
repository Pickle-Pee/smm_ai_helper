"""Offline provider-envelope experiment with unchanged local acceptance."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest
from jsonschema import Draft202012Validator

from app.config import Settings, settings
from app.llm.openai_text import ModelResponseError, ModelResponseFailureReason
from app.module_execution import UpstreamExecutionResult
from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors import PositioningExecutor, ExecutorOutputError, build_module_executor_registry
from app.module_execution.executors import common
from app.module_execution.executors.positioning_provider_schema import minimal_positioning_schema
from app.module_execution.executors.positioning_observation_schema import positioning_observation_schema
from app.module_execution.executors.provider_schema import nodes
from app.module_registry import ModuleId
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.orchestration_runtime.service import evaluate_result
from app.orchestration_runtime.worker import transient
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import FakeModel, analyzer, dispatch, request
from tests.test_positioning_seed_contract import seed_request
from tests.test_production_graph_worker import queue
from tests.test_strategy_intelligence import IntelligenceModel, valid_request
from tools.positioning_diagnostics import capture_request
from tools.positioning_schema_experiment import compare, synthetic_request


@pytest.mark.parametrize("job,alternative", [(True, True), (False, True), (True, False), (False, False)])
@pytest.mark.parametrize("parents", [False, True])
def test_same_local_result_and_gates_for_both_provider_schemas(monkeypatch, job, alternative, parents):
    invocation = replace(seed_request(job, alternative), execution_id="a" * 32)
    if parents:
        predecessor = dispatch(request(ModuleId.COMPETITOR_ANALYSIS))
        invocation = replace(invocation, upstream_results=(UpstreamExecutionResult(
            producer_node_id="competitor_analysis", result=predecessor),))
    validators = []
    factory = common.Draft202012Validator
    def track(schema):
        validators.append(deepcopy(schema))
        return factory(schema)
    monkeypatch.setattr(common, "Draft202012Validator", track)
    results, calls = [], []
    for enabled in (False, True):
        fake = FakeModel(use_parents=parents)
        results.append(asyncio.run(PositioningExecutor(model_call=fake,
            minimal_provider_schema=enabled).execute(invocation)))
        calls.append(fake.calls[0])
        assert Draft202012Validator(calls[-1]["response_schema"]).is_valid(common.plain(results[-1].payload))
        quality = evaluate_result(invocation.execution_id, results[-1], invocation.upstream_results)
        assert fully_accepted(results[-1], quality["accepted_result_ids"], quality["accepted_claim_ids"])
        assert len(fake.calls) == 1
    assert results[0] == results[1]
    assert validators[0] == validators[1]
    assert positioning_observation_schema(validators[0]) == calls[0]["response_schema"]
    assert calls[1].pop("response_schema") == positioning_observation_schema(minimal_positioning_schema(), minimal=True)
    calls[0].pop("response_schema")
    assert calls[0] == calls[1]


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("mutation,stage", [
    (lambda p,d: p["outputs"][0].update(evidence_ids=["evd_unknown"]), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(parent_claim_ids=["clm_unknown"]), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(evidence_ids=[], parent_claim_ids=[]), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(kind="OBSERVATION"), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(output_name="unknown"), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(confidence="CERTAIN"), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(text="x" * 4001), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(text="  "), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(extra="forbidden"), "schema_invalid"),
    (lambda p,d: p["outputs"][0].update(text=42), "schema_invalid"),
    (lambda p,d: p.update(assumptions=["x"] * 13), "schema_invalid"),
    (lambda p,d: p["outputs"].pop(), "output_coverage_invalid"),
    (lambda p,d: p["outputs"][0]["evidence_ids"].append(p["outputs"][0]["evidence_ids"][0]), "support_identity_invalid"),
    (lambda p,d: next(s for s in p["outputs"] if s["output_name"] == "RTB").update(evidence_ids=[
        next(e["evidence_id"] for e in d["local_evidence"] if e["input_key"] == "product")]), "statement_semantics_invalid"),
])
def test_rejections_still_fail_closed_locally(enabled, mutation, stage):
    fake = FakeModel(mutation)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=fake, minimal_provider_schema=enabled).execute(seed_request(False, False)))
    assert caught.value.stage.value == stage
    assert len(fake.calls) == 1 and not transient(caught.value)


def test_provider_superset_is_deliberate_and_cannot_mutate_validator():
    invocation = seed_request(False, False)
    fake = FakeModel(lambda p,d: p["outputs"][0].update(evidence_ids=["evd_fabricated"]))
    async def capability(**kwargs):
        raw = await fake(**kwargs)
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(json.loads(raw))
        kwargs["response_schema"].clear()
        return raw
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PositioningExecutor(model_call=capability, minimal_provider_schema=True).execute(invocation))
    assert minimal_positioning_schema()["properties"]


@pytest.mark.parametrize("module", [ModuleId.COMPETITOR_ANALYSIS, ModuleId.CREATOR,
    ModuleId.MARKET_ANALYSIS, ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
def test_other_modules_including_numeric_support_have_identical_arguments(module):
    invocation = request(module) if module in (ModuleId.COMPETITOR_ANALYSIS, ModuleId.CREATOR) else valid_request(module)
    calls, results = [], []
    for enabled in (False, True):
        fake = IntelligenceModel(use_parents=True)
        registry = build_module_executor_registry(model_call=fake, analyzer=analyzer(), market_analyzer=analyzer(),
            registry_version="1.3.0", positioning_minimal_provider_schema=enabled)
        results.append(asyncio.run(registry.resolve(module.value.lower() + ".v1").execute(invocation)))
        calls.append(fake.calls)
    assert calls[0] == calls[1] and results[0] == results[1]


@pytest.mark.parametrize("enabled", [False, True])
def test_production_registry_and_http_payload(monkeypatch, enabled):
    monkeypatch.setattr(settings, "POSITIONING_MINIMAL_PROVIDER_SCHEMA_ENABLED", enabled)
    invocation = seed_request(True, True)
    seen = []
    def respond(req):
        seen.append(json.loads(req.content))
        body = seen[-1]
        arguments = dict(text=body["input"][1]["content"], response_schema=body["text"]["format"]["schema"])
        # This synchronous handler builds the same valid local response.
        data = json.loads(arguments["text"])
        payload = {"outputs": [{"output_name": name, "text": "Supported hypothesis", "kind": "HYPOTHESIS",
            "confidence": "MEDIUM", "evidence_ids": [e["evidence_id"] for e in data["local_evidence"]],
            "parent_claim_ids": []} for name in data["expected_outputs"]], "assumptions": [], "limitations": []}
        return httpx.Response(200, json={"status": "completed", "output_text": json.dumps(payload)})
    install_transport(monkeypatch, respond)
    runtime = build_production_graph_runtime(queue=queue(), analyzer=analyzer())
    asyncio.run(runtime.executors.resolve("positioning.v1").execute(invocation))
    baseline = asyncio.run(capture_request(invocation, model=settings.DEFAULT_TEXT_MODEL_HARD)).payload
    expected = deepcopy(baseline)
    expected["text"]["format"]["schema"] = positioning_observation_schema(
        minimal_positioning_schema() if enabled else expected["text"]["format"]["schema"], minimal=enabled)
    assert seen == [expected]
    assert Settings.model_fields["POSITIONING_MINIMAL_PROVIDER_SCHEMA_ENABLED"].default is False


@pytest.mark.parametrize("options", [{"provider_schema_projection": True}, {"product_support_wire": True}])
def test_other_positioning_experiments_cannot_mix(options):
    with pytest.raises(ValueError):
        PositioningExecutor(model_call=FakeModel(), minimal_provider_schema=True, **options)


@pytest.mark.parametrize("invalid", [1, None, "true"])
def test_flag_requires_boolean(invalid):
    with pytest.raises(TypeError):
        PositioningExecutor(model_call=FakeModel(), minimal_provider_schema=invalid)


@pytest.mark.parametrize("enabled", [False, True])
def test_empty_incomplete_response_is_still_rejected_without_retry(monkeypatch, enabled):
    from app.orchestration_runtime.model_adapter import production_model_call
    seen = []
    def respond(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"status": "incomplete", "output": [],
            "incomplete_details": {"reason": "max_output_tokens"},
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                      "output_tokens_details": {"reasoning_tokens": 0}}})
    install_transport(monkeypatch, respond)
    with pytest.raises(ModelResponseError) as caught:
        asyncio.run(PositioningExecutor(model_call=production_model_call,
            minimal_provider_schema=enabled).execute(seed_request(True, True)))
    assert caught.value.reason is ModelResponseFailureReason.INCOMPLETE_EMPTY_MAX_OUTPUT_TOKENS
    assert len(seen) == 1 and seen[0]["max_output_tokens"] == 16000


def test_offline_comparison_hashes_real_wire_and_has_no_live_option(monkeypatch):
    # No real HTTP client is ever constructed, even without usable credentials.
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("real client constructed"))
    async def check():
        first = await compare(synthetic_request(), model=settings.DEFAULT_TEXT_MODEL_HARD)
        second = await compare(synthetic_request(), model=settings.DEFAULT_TEXT_MODEL_HARD)
        assert first == second
        assert first["live_calls"] == 0 and first["hypothesis"] == "unproven"
        assert first["max_output_tokens"] == 16000 and first["reasoning"] == {"effort": "low"}
        assert first["original"]["http_body"]["sha256"] != first["minimal"]["http_body"]["sha256"]
        assert first["minimal"]["schema"]["bytes"] < first["original"]["schema"]["bytes"] / 5
    asyncio.run(check())
    schema = minimal_positioning_schema()
    Draft202012Validator.check_schema(schema)
    for node in nodes(schema):
        assert set(node) <= {"type", "properties", "required", "additionalProperties", "items"}
        if node.get("type") == "object":
            assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
