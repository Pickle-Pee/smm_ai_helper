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
    assert all("anyOf" not in node for node in nodes(schema) if "properties" in node)
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


def test_wire_expresses_empty_constraint_contract(invocation):
    captured = asyncio.run(capture_request(invocation))
    schema = strategic_parent_wire_schema(captured.arguments["response_schema"], strategic_parents(invocation))
    payload = wire_payload(json.loads(captured.arguments["text"]), schema)
    assert Draft202012Validator(schema).is_valid(payload)
    payload["experiments"][0]["time_resource_constraints"] = ["Duration 14 days"]
    assert not Draft202012Validator(schema).is_valid(payload)


@pytest.mark.parametrize("projection", [False, True])
def test_wire_preserves_exact_supplied_constraints(invocation, projection):
    from tests.test_module_executors import fact
    constraints = ("Duration 14 days", "Budget 500 dollars")
    request = replace(invocation, context_packet=replace(invocation.context_packet,
        constraints=(constraints[0],),
        known_facts=(*invocation.context_packet.known_facts, fact("budget", constraints[1]))))
    calls = []
    async def model(**kwargs):
        calls.append(True)
        schema = kwargs["response_schema"]
        field = schema["$defs"]["ExperimentDesign"]["properties"]["time_resource_constraints"]
        assert field["minItems"] == field["maxItems"] == 2
        assert set(field["items"]["enum"]) == set(constraints)
        payload = wire_payload(json.loads(kwargs["text"]), schema)
        for design in payload["experiments"]:
            design["time_resource_constraints"] = list(constraints)
        assert Draft202012Validator(schema).is_valid(payload)
        for invalid in ([], [constraints[0]], [*constraints, "Extra constraint"],
                        [constraints[0], "Budget is 500 dollars"]):
            bad = deepcopy(payload)
            bad["experiments"][0]["time_resource_constraints"] = invalid
            assert not Draft202012Validator(schema).is_valid(bad)
        return json.dumps(payload)
    result = asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
        provider_schema_projection=projection).execute(request))
    assert calls == [True]
    assert all(tuple(d["time_resource_constraints"]) == constraints for d in result.payload["experiments"])
    quality = evaluate_result(request.execution_id, result, request.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])


@pytest.mark.parametrize("constraints", [("x" * 301,), ("",), tuple(str(i) for i in range(9))])
def test_unrepresentable_constraints_refused_before_provider(invocation, constraints):
    from app.module_execution.errors import ModuleExecutionContractError
    captured = asyncio.run(capture_request(invocation))
    with pytest.raises(ModuleExecutionContractError):
        strategic_parent_wire_schema(captured.arguments["response_schema"], strategic_parents(invocation), constraints)


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



def test_provider_design_schema_rejects_invented_numeric_intervention(invocation):
    baseline = asyncio.run(capture_request(invocation))
    wire = strategic_parent_wire_schema(baseline.arguments["response_schema"], strategic_parents(invocation))
    payload = wire_payload(json.loads(baseline.arguments["text"]), wire)
    payload["experiments"][1]["intervention"] = "Compare 2 new messages"
    # Canonical semantics already reject this; provider generation must express it.
    assert not Draft202012Validator(wire).is_valid(payload)



def replace_parent_assertion(request, claim_id, value):
    upstream = []
    for item in request.upstream_results:
        if any(c.claim_id == claim_id for c in item.result.normalized_result.claims):
            normalized = replace(item.result.normalized_result, claims=tuple(
                replace(c, value=value) if c.claim_id == claim_id else c
                for c in item.result.normalized_result.claims))
            item = replace(item, result=replace(item.result,
                payload=result_to_json(item.result)["payload"], normalized_result=normalized))
        upstream.append(item)
    return replace(request, upstream_results=tuple(upstream))


@pytest.mark.parametrize("field", ["hypothesis", "target_metric", "intervention", "expected_signal", "failure_condition", "minimum_required_inputs"])
def test_design_numeric_schema_exact_full_assertions_and_bounds(invocation, field):
    baseline = asyncio.run(capture_request(invocation))
    original = baseline.arguments["response_schema"]
    before = deepcopy(original)
    quote = "Test a 20% directional uplift hypothesis"
    wire = strategic_parent_wire_schema(original, strategic_parents(invocation), strategic_assertions=(quote, "x" * 300 + "2", "Qualitative only"))
    payload = wire_payload(json.loads(baseline.arguments["text"]), wire)
    def set_text(value):
        payload["experiments"][0][field] = [value] if field == "minimum_required_inputs" else value
    for text, allowed in [(quote, True), ("Qualitative design without invented quantities", True),
                          ("20% directional uplift", False), (quote + " after launch", False),
                          ("Test a 40% directional uplift hypothesis", False),
                          ("Compare 2 variants", False), ("", False), ("x" * 301, False),
                          ("x" * 300 + "2", False)]:
        set_text(text)
        assert Draft202012Validator(wire).is_valid(payload) is allowed
    assert original == before
    assert original["$defs"]["ExperimentStatement"]["properties"]["text"] == before["$defs"]["ExperimentStatement"]["properties"]["text"]
    assert wire["$defs"]["ExperimentDesign"]["properties"]["time_resource_constraints"]["maxItems"] == 0


@pytest.mark.parametrize("projection", [False, True])
def test_supported_numeric_assertion_uses_authoritative_parents_and_original_guard(invocation, projection):
    numeric_id, *other_ids = strategic_parents(invocation)
    quote = "Test a 20% directional uplift hypothesis"
    request = replace_parent_assertion(invocation, numeric_id, quote)
    async def model(**kwargs):
        payload = wire_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        for design in payload["experiments"]:
            design["related_strategic_claim_ids"] = [numeric_id]
        payload["experiments"][0]["intervention"] = quote
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    result = asyncio.run(ExperimentsExecutor(model_call=model,
        strategic_parent_wire=True, provider_schema_projection=projection).execute(request))
    assert result.payload["experiments"][0]["intervention"] == quote
    assert "wire_contract_version" not in result.payload
    async def wrong_citation(**kwargs):
        payload = json.loads(await model(**kwargs))
        payload["experiments"][0]["related_strategic_claim_ids"] = [other_ids[0]]
        # The request-wide provider enum permits it, but its cited source does not.
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=wrong_citation,
            strategic_parent_wire=True, provider_schema_projection=projection).execute(request))
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_structured_numeric_context_does_not_enter_design_assertion_allowlist(invocation):
    numeric_id = next(iter(strategic_parents(invocation)))
    quote = "Test a 20% directional uplift hypothesis"
    value = json.dumps({"summary":"Qualitative strategic hypothesis", "items":["Validate the message"],
        "numeric_context":[{"support_id":"evd_context", "quote":quote, "attribution":"supplied_context"}]})
    request = replace_parent_assertion(invocation, numeric_id, value)
    async def model(**kwargs):
        design = kwargs["response_schema"]["$defs"]["ExperimentDesign"]["properties"]
        assert "anyOf" not in design["intervention"]
        payload = wire_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        payload["experiments"][0]["intervention"] = quote
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True).execute(request))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_qualitative_design_wire_does_not_change_exact_constraints(invocation):
    baseline = asyncio.run(capture_request(invocation))
    wire = strategic_parent_wire_schema(baseline.arguments["response_schema"],
        strategic_parents(invocation), constraints=("Budget 500 dollars",), strategic_assertions=("Test 2 messages",))
    payload = wire_payload(json.loads(baseline.arguments["text"]), wire)
    for design in payload["experiments"]:
        design["time_resource_constraints"] = ["Budget 500 dollars"]
    assert Draft202012Validator(wire).is_valid(payload)
    payload["experiments"][0]["time_resource_constraints"] = ["Budget 600 dollars"]
    assert not Draft202012Validator(wire).is_valid(payload)


def test_design_schema_flags_off_remains_original(invocation):
    baseline = asyncio.run(capture_request(invocation))
    executor = ExperimentsExecutor(model_call=AsyncMock(), strategic_parent_wire=False)
    original = deepcopy(baseline.arguments["response_schema"])
    assert executor.wire_schema_for(invocation, original, ()) is original
    assert original == baseline.arguments["response_schema"]
    assert "pattern" not in original["$defs"]["ExperimentDesign"]["properties"]["intervention"]



def test_numeric_design_additions_keep_complete_provider_budget_guard(invocation):
    from app.module_execution.errors import ModuleExecutionContractError
    baseline = asyncio.run(capture_request(invocation))
    assertions = tuple(f"Supplied numerical hypothesis {i}" for i in range(1001))
    with pytest.raises(ModuleExecutionContractError, match="exceeds provider bounds"):
        strategic_parent_wire_schema(baseline.arguments["response_schema"],
            strategic_parents(invocation), strategic_assertions=assertions)


def test_unicode_decimal_numeric_guard_remains_authoritative(invocation):
    async def model(**kwargs):
        payload = wire_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        payload["experiments"][0]["intervention"] = "Compare \u0662 variants"
        # The portable ASCII generation pattern deliberately makes no Unicode proof.
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True).execute(invocation))
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID



def test_numeric_design_enum_is_shared_direct_ref_and_read_only_equivalent(invocation):
    baseline = asyncio.run(capture_request(invocation))
    original = baseline.arguments["response_schema"]
    original_before = deepcopy(original)
    quotes = ["Test a 20% directional uplift hypothesis", "Compare 2 supplied messages"]
    wire = strategic_parent_wire_schema(original, strategic_parents(invocation), strategic_assertions=quotes)
    shared = wire["$defs"]["AllowedExperimentNumericAssertion"]
    assert shared == {"type":"string", "minLength":1, "maxLength":300, "enum":sorted(quotes)}
    assert sum(node.get("enum") == sorted(quotes) for node in nodes(wire)) == 1
    design = wire["$defs"]["ExperimentDesign"]["properties"]
    fields = ("hypothesis", "target_metric", "intervention", "expected_signal", "failure_condition", "minimum_required_inputs")
    for name in fields:
        text = design[name]["items"] if name == "minimum_required_inputs" else design[name]
        assert text["anyOf"][1] == {"$ref":"#/$defs/AllowedExperimentNumericAssertion"}
        assert text["anyOf"][0]["minLength"] == 1 and text["anyOf"][0]["maxLength"] == 300
    # Inline a copy of the shared definition to reproduce the previous encoding.
    inline = deepcopy(wire)
    for node in list(nodes(inline)):
        if node == {"$ref":"#/$defs/AllowedExperimentNumericAssertion"}:
            node.clear()
            node.update(deepcopy(shared))
    inline["$defs"].pop("AllowedExperimentNumericAssertion")
    before = deepcopy(wire)
    direct_validator, inline_validator = Draft202012Validator(wire), Draft202012Validator(inline)
    payload = wire_payload(json.loads(baseline.arguments["text"]), wire)
    for name in fields:
        for value in (*quotes, "Qualitative assertion", "20% uplift", "Compare 4 supplied messages", "", "x" * 301):
            payload["experiments"][0][name] = [value] if name == "minimum_required_inputs" else value
            assert direct_validator.is_valid(payload) == inline_validator.is_valid(payload)
        payload = wire_payload(json.loads(baseline.arguments["text"]), wire)
    assert wire == before and original == original_before


def test_numeric_design_definition_collision_refuses(invocation):
    from app.module_execution.errors import ModuleExecutionContractError
    baseline = asyncio.run(capture_request(invocation))
    original = deepcopy(baseline.arguments["response_schema"])
    original["$defs"]["AllowedExperimentNumericAssertion"] = {"type":"string"}
    before = deepcopy(original)
    with pytest.raises(ModuleExecutionContractError, match="Unexpected strategic parent wire contract"):
        strategic_parent_wire_schema(original, strategic_parents(invocation), strategic_assertions=("Test 2 messages",))
    assert original == before



def test_provider_statement_schema_rejects_invented_numeric_paraphrase(invocation):
    baseline = asyncio.run(capture_request(invocation))
    wire = strategic_parent_wire_schema(baseline.arguments["response_schema"], strategic_parents(invocation))
    payload = wire_payload(json.loads(baseline.arguments["text"]), wire)
    payload["outputs"][1]["text"] = "Compare 2 alternative messages for the audience"
    assert not Draft202012Validator(wire).is_valid(payload)



@pytest.mark.parametrize("projection", [False, True])
@pytest.mark.parametrize("source", ["local_string", "local_object", "accepted_nonstrategic_parent"])
def test_statement_full_numeric_assertion_scope_and_actual_citation(invocation, projection, source):
    from tests.test_module_executors import fact
    quote = "Supplied scenario contains 20 qualified inquiries"
    parent_id = "clm_z_additional_recommendation"
    if source == "accepted_nonstrategic_parent":
        request = replace_parent_assertion(invocation, parent_id, quote)
    else:
        value = quote if source == "local_string" else {"scenario": quote}
        request = replace(invocation, context_packet=replace(invocation.context_packet,
            known_facts=(*invocation.context_packet.known_facts, fact("numeric_wire_test", value))))
        if source == "local_object":
            quote = json.dumps(value, ensure_ascii=False)
    baseline = asyncio.run(capture_request(request))
    captured = []
    async def model(**kwargs):
        captured.append(deepcopy(kwargs))
        schema = kwargs["response_schema"]
        enum = schema["$defs"]["AllowedExperimentStatementNumericAssertion"]["enum"]
        assert quote in enum
        assert sum(node.get("enum") == enum for node in nodes(schema)) == 1
        payload = wire_payload(json.loads(kwargs["text"]), schema)
        payload["outputs"][1]["text"] = quote
        if source == "accepted_nonstrategic_parent":
            payload["outputs"][1]["parent_claim_ids"] = [parent_id]
        else:
            data = json.loads(kwargs["text"])
            eid = next(item["evidence_id"] for item in data["local_evidence"]
                       if item["value"] == value)
            payload["outputs"][1]["evidence_ids"] = [eid]
        return json.dumps(payload)
    executor = ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
        provider_schema_projection=projection)
    result = asyncio.run(executor.execute(request))
    assert result.payload["outputs"][1]["text"] == quote
    assert captured[0]["text"] == baseline.arguments["text"]
    assert captured[0]["instruction"] == baseline.arguments["instruction"]
    assert result_from_json(result_to_json(result)) == result
    async def uncited(**kwargs):
        payload = json.loads(await model(**kwargs))
        payload["outputs"][1]["evidence_ids"] = []
        payload["outputs"][1]["parent_claim_ids"] = []
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=uncited, strategic_parent_wire=True,
            provider_schema_projection=projection).execute(request))
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_statement_numeric_enum_bounds_exactness_directref_and_immutability(invocation):
    baseline = asyncio.run(capture_request(invocation))
    original = baseline.arguments["response_schema"]
    before = deepcopy(original)
    quote = "Supplied 20 qualified inquiries"
    bound = "x" * 3999 + "2"
    wire = strategic_parent_wire_schema(original, strategic_parents(invocation),
        statement_assertions=(quote, bound, "x" * 4000 + "2", "Qualitative only"))
    shared = wire["$defs"]["AllowedExperimentStatementNumericAssertion"]
    assert shared == {"type":"string", "minLength":1, "maxLength":4000, "enum":sorted([quote, bound])}
    text = wire["$defs"]["ExperimentStatement"]["properties"]["text"]
    assert text["anyOf"][1] == {"$ref":"#/$defs/AllowedExperimentStatementNumericAssertion"}
    assert text["anyOf"][0]["minLength"] == 1 and text["anyOf"][0]["maxLength"] == 4000
    wire_before = deepcopy(wire)
    payload = wire_payload(json.loads(baseline.arguments["text"]), wire)
    for value, accepted in [(quote,True), (bound,True), ("Qualitative text",True),
                            ("20 qualified inquiries",False), (quote + " after launch",False),
                            ("Supplied 40 qualified inquiries",False), ("Compare 2 variants",False),
                            ("",False), ("x" * 4000 + "2",False)]:
        payload["outputs"][1]["text"] = value
        assert Draft202012Validator(wire).is_valid(payload) is accepted
    assert original == before and wire == wire_before


def test_statement_structured_parent_numeric_context_is_excluded(invocation):
    quote = "Supplied 37 qualified inquiries"
    value = json.dumps({"summary":"Qualitative strategic hypothesis", "items":["Validate the message"],
        "numeric_context":[{"support_id":"evd_context", "quote":quote, "attribution":"supplied_context"}]})
    request = replace_parent_assertion(invocation, "clm_z_additional_recommendation", value)
    async def model(**kwargs):
        schema = kwargs["response_schema"]
        allowed = schema["$defs"].get("AllowedExperimentStatementNumericAssertion", {}).get("enum", [])
        assert quote not in allowed and value not in allowed
        payload = wire_payload(json.loads(kwargs["text"]), schema)
        payload["outputs"][1].update(text=quote, parent_claim_ids=["clm_z_additional_recommendation"])
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True).execute(request))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_statement_definition_collision_and_combined_corpus_budget_refuse(invocation):
    from app.module_execution.errors import ModuleExecutionContractError
    baseline = asyncio.run(capture_request(invocation))
    original = deepcopy(baseline.arguments["response_schema"])
    original["$defs"]["AllowedExperimentStatementNumericAssertion"] = {"type":"string"}
    before = deepcopy(original)
    with pytest.raises(ModuleExecutionContractError, match="Unexpected strategic parent wire contract"):
        strategic_parent_wire_schema(original, strategic_parents(invocation))
    assert original == before
    with pytest.raises(ModuleExecutionContractError, match="exceeds provider bounds"):
        strategic_parent_wire_schema(baseline.arguments["response_schema"], strategic_parents(invocation),
            strategic_assertions=tuple(f"d{i}" for i in range(501)),
            statement_assertions=tuple(f"s{i}" for i in range(501)))


def test_statement_flags_off_keeps_original_schema(invocation):
    baseline = asyncio.run(capture_request(invocation))
    executor = ExperimentsExecutor(model_call=AsyncMock(), strategic_parent_wire=False)
    original = deepcopy(baseline.arguments["response_schema"])
    before = deepcopy(original)
    assert executor.wire_schema_for(invocation, original, ()) is original
    assert original == before
    assert "pattern" not in original["$defs"]["ExperimentStatement"]["properties"]["text"]
