"""Explicit eligible selection; canonical v1 remains the final authority."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator

from app.config import Settings, settings
from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors import ExperimentsExecutor
from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage, parent_claims
from app.module_execution.executors.experiments import strategic_parents
from app.module_execution.executors.experiments_support_wire import (
    WIRE_VERSION, strategic_parent_wire_schema, decode_strategic_parent_wire,
)
from app.module_execution.executors.provider_schema import nodes, SchemaProjectionError
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.orchestration_runtime.serialization import result_to_json, result_from_json
from app.orchestration_runtime.service import evaluate_result
from tests.experiments_provider import full_payload, with_nonstrategic_parent
from tests.test_experiments_diagnostics import restored
from tests.test_module_executors import analyzer
from tests.test_production_graph_worker import queue
from tools.experiments_diagnostics import capture_request


@pytest.fixture(scope="module")
def invocation():
    return with_nonstrategic_parent(restored())


def wire_payload(data, schema):
    selected = schema["$defs"]["AllowedStrategicParentId"]["enum"][0]
    payload = full_payload(data)
    payload["wire_contract_version"] = WIRE_VERSION
    for statement in payload["outputs"]:
        statement.update(strategic_parent_id=selected, parent_claim_ids=[])
    for design in payload["experiments"]:
        design["related_strategic_claim_ids"] = [selected]
    return payload


@pytest.mark.parametrize("projection", [False, True])
def test_full_wire_original_gates_and_v1_serialization(invocation, projection):
    calls = []
    async def model(**kwargs):
        calls.append(deepcopy(kwargs))
        payload = wire_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        for statement in payload["outputs"]:
            statement["parent_claim_ids"] = ["clm_z_additional_recommendation"]
        return json.dumps(payload)
    result = asyncio.run(ExperimentsExecutor(model_call=model,
        strategic_parent_wire=True, provider_schema_projection=projection).execute(invocation))
    assert len(calls) == 1
    eligible = strategic_parents(invocation)
    schema = calls[0]["response_schema"]
    assert set(schema["$defs"]["AllowedStrategicParentId"]["enum"]) == set(eligible)
    assert set(schema["$defs"]["AllowedParentClaimId"]["enum"]) == set(parent_claims(invocation))
    assert all("anyOf" not in node for node in nodes(schema))
    assert schema["$defs"]["ExperimentDesign"]["properties"]["related_strategic_claim_ids"]["items"] == {"$ref": "#/$defs/AllowedStrategicParentId"}
    for statement in result.payload["outputs"]:
        assert set(statement["parent_claim_ids"]) & eligible.keys()
        assert "clm_z_additional_recommendation" in statement["parent_claim_ids"]
        assert "strategic_parent_id" not in statement
    assert "wire_contract_version" not in result.payload
    assert result.schema_version == "experiments.payload.v1"
    assert result_from_json(result_to_json(result)) == result
    quality = evaluate_result(invocation.execution_id, result, invocation.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(wire_contract_version="experiments.wire.unknown"),
    lambda p: p["outputs"][0].update(strategic_parent_id="clm_unknown"),
    lambda p: p["outputs"][0].update(strategic_parent_id="clm_z_additional_recommendation"),
    lambda p: p["outputs"][0].pop("strategic_parent_id"),
    lambda p: p["outputs"][0].update(parent_claim_ids=["clm_unknown"]),
    lambda p: p["outputs"][0].update(parent_claim_ids=["clm_z_additional_recommendation"] * 2),
    lambda p: p["outputs"][0].update(text="Guaranteed 90% uplift"),
    lambda p: p["experiments"][0].update(expected_signal="Expected uplift 20%"),
    lambda p: p["experiments"][0].update(time_resource_constraints=["Budget 500 dollars"]),
    lambda p: p["experiments"][0].update(related_strategic_claim_ids=["clm_z_additional_recommendation"]),
    lambda p: p["experiments"][0]["related_strategic_claim_ids"].append(p["experiments"][0]["related_strategic_claim_ids"][0]),
])
def test_wire_does_not_weaken_original_rules(invocation, mutation):
    calls = []
    async def model(**kwargs):
        calls.append(True)
        payload = wire_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        mutation(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True).execute(invocation))
    assert calls == [True]


def test_bounds_overlap_and_duplicate_no_repair(invocation):
    original = asyncio.run(capture_request(invocation)).arguments["response_schema"]
    # Independently exercise the maximal schema/decoder boundary with known IDs.
    ids = [f"clm_bound_{i}" for i in range(32)]
    original["$defs"]["AllowedParentClaimId"]["enum"] = ids
    wire = strategic_parent_wire_schema(original, [ids[0]])
    payload = wire_payload(json.loads(asyncio.run(capture_request(invocation)).arguments["text"]), wire)
    for output in payload["outputs"]:
        output["parent_claim_ids"] = ids[1:]
    assert Draft202012Validator(wire).is_valid(payload)
    decoded = decode_strategic_parent_wire(payload, [ids[0]])
    assert all(statement["parent_claim_ids"] == ids for statement in decoded["outputs"])
    assert Draft202012Validator(original).is_valid(decoded)
    payload["outputs"][0]["parent_claim_ids"] = ids
    assert not Draft202012Validator(wire).is_valid(payload)
    payload["outputs"][0]["parent_claim_ids"] = [ids[0]]
    assert decode_strategic_parent_wire(payload, [ids[0]])["outputs"][0]["parent_claim_ids"] == [ids[0]]
    payload["outputs"][0]["parent_claim_ids"] *= 2
    with pytest.raises(ValueError, match="Duplicate"):
        decode_strategic_parent_wire(payload, [ids[0]])


@pytest.mark.parametrize("wire", [False, True])
@pytest.mark.parametrize("projection", [False, True])
def test_independent_default_off_runtime_switches(monkeypatch, wire, projection):
    monkeypatch.setattr(settings, "EXPERIMENTS_STRATEGIC_PARENT_WIRE_ENABLED", wire)
    monkeypatch.setattr(settings, "EXPERIMENTS_SCHEMA_PROJECTION_ENABLED", projection)
    executor = build_production_graph_runtime(queue=queue(), analyzer=analyzer()).executors.resolve("experiments.v1")
    assert executor._strategic_parent_wire is wire
    assert executor._provider_schema_projection is projection
    assert Settings.model_fields["EXPERIMENTS_STRATEGIC_PARENT_WIRE_ENABLED"].default is False


@pytest.mark.parametrize("field", ["parent_claim_ids", "evidence_ids"])
def test_original_first_output_rejects_duplicates_before_union(invocation, field):
    async def model(**kwargs):
        payload = full_payload(json.loads(kwargs["text"]))
        # Keep design refs eligible even in the mixed-parent invocation.
        eligible = next(iter(strategic_parents(invocation)))
        for design in payload["experiments"]:
            design["related_strategic_claim_ids"] = [eligible]
        if field == "parent_claim_ids":
            payload["outputs"][0][field] = [eligible, eligible]
        else:
            evidence = json.loads(kwargs["text"])["local_evidence"][0]["evidence_id"]
            payload["outputs"][0][field] = [evidence, evidence]
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model).execute(invocation))
    assert caught.value.stage is OutputFailureStage.SUPPORT_IDENTITY_INVALID


def test_original_schema_survives_provider_mutation(invocation):
    async def model(**kwargs):
        payload = wire_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        kwargs["response_schema"].clear()
        payload["outputs"][0]["text"] = ""
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True).execute(invocation))


def test_projection_proof_refusal_prevents_provider(monkeypatch, invocation):
    from app.module_execution.executors import experiments
    def refuse(schema):
        raise SchemaProjectionError("proof_refused")
    monkeypatch.setattr(experiments, "collapse_redundant_support_anyof", refuse)
    model = AsyncMock()
    with pytest.raises(SchemaProjectionError):
        asyncio.run(ExperimentsExecutor(model_call=model, provider_schema_projection=True).execute(invocation))
    model.assert_not_called()


@pytest.mark.parametrize("flag", [None, "true", 1])
def test_wire_constructor_is_typed(flag):
    with pytest.raises(TypeError):
        ExperimentsExecutor(model_call=AsyncMock(), strategic_parent_wire=flag)


@pytest.mark.parametrize("kind,accepted", [("HYPOTHESIS", True), ("RECOMMENDATION", True), ("OBSERVATION", False), ("INFERENCE", False)])
def test_wire_kinds_align_existing_guard(invocation, kind, accepted):
    captured = {}
    async def model(**kwargs):
        payload = wire_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        payload["outputs"][0]["kind"] = kind
        captured.update(schema=kwargs["response_schema"], payload=payload)
        return json.dumps(payload)
    executor = ExperimentsExecutor(model_call=model, strategic_parent_wire=True)
    if accepted:
        asyncio.run(executor.execute(invocation))
    else:
        with pytest.raises(ExecutorOutputError) as caught:
            asyncio.run(executor.execute(invocation))
        assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID
    assert Draft202012Validator(captured["schema"]).is_valid(captured["payload"]) is accepted
    original = asyncio.run(capture_request(invocation)).arguments["response_schema"]
    decoded = decode_strategic_parent_wire(captured["payload"], strategic_parents(invocation))
    assert Draft202012Validator(original).is_valid(decoded)


def test_wire_no_strategic_parent_is_blocked(invocation):
    model = AsyncMock()
    result = asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True).execute(
        replace(invocation, upstream_results=())))
    assert result.normalized_result.module_status.value == "BLOCKED"
    model.assert_not_called()



def test_hypothesis_from_wrong_module_cannot_be_selected(invocation):
    from app.module_execution import UpstreamExecutionResult
    from app.module_registry import ModuleId
    from app.marketing_orchestrator.quality_gates.contracts import ClaimType
    original = invocation.upstream_results[0].result
    claim = replace(original.normalized_result.claims[0], claim_id="clm_wrong_module_hypothesis", claim_type=ClaimType.HYPOTHESIS)
    upstream = replace(original, module_id=ModuleId.MARKET_ANALYSIS,
        payload=result_to_json(original)["payload"], normalized_result=replace(
            original.normalized_result, result_id="res_wrong_module", module_id=ModuleId.MARKET_ANALYSIS, claims=(claim,)))
    request = replace(invocation, upstream_results=(*invocation.upstream_results,
        UpstreamExecutionResult(producer_node_id="wrong_module", result=upstream)))
    assert claim.claim_id in parent_claims(request) and claim.claim_id not in strategic_parents(request)
    async def model(**kwargs):
        payload = wire_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        payload["outputs"][0]["strategic_parent_id"] = claim.claim_id
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True).execute(request))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_wire_is_strict_closed_and_keeps_bounds(invocation):
    original = asyncio.run(capture_request(invocation)).arguments["response_schema"]
    before = deepcopy(original)
    wire = strategic_parent_wire_schema(original, strategic_parents(invocation))
    assert original == before
    for node in nodes(wire):
        if "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
    statement = wire["$defs"]["ExperimentStatement"]["properties"]
    assert statement["parent_claim_ids"]["minItems"] == 0
    assert statement["parent_claim_ids"]["maxItems"] == 31
    assert statement["evidence_ids"]["maxItems"] == 32
    assert original["$defs"]["ExperimentStatement"]["properties"]["parent_claim_ids"]["minItems"] == 1


def test_duplicate_evidence_is_not_repaired_by_wire(invocation):
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        payload = wire_payload(data, kwargs["response_schema"])
        payload["outputs"][0]["evidence_ids"] = [data["local_evidence"][0]["evidence_id"]] * 2
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True).execute(invocation))
