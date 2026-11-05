"""Typed additional support sets; V2 malformed arrays are never repaired."""
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
from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage
from app.module_execution.executors.experiments import strategic_parents
from app.module_execution.executors.experiments_support_selection import (
    WIRE_VERSION, EVIDENCE_BASIS_NOTES, EVIDENCE_BASIS_DEFINITION, OTHER_STATEMENT_DEFINITION,
)
from app.orchestration_runtime.serialization import result_to_json, result_from_json
from app.orchestration_runtime.service import evaluate_result
from tests.test_experiments_support_wire import invocation, wire_payload, replace_parent_assertion


def typed_payload(data, schema):
    payload = wire_payload(data, schema)
    payload["wire_contract_version"] = WIRE_VERSION
    choices = data["experiments_support_selection_catalog"]
    for statement in payload["outputs"]:
        if statement["output_name"] == "evidence_basis":
            statement["text"] = EVIDENCE_BASIS_NOTES[0]
        statement.pop("evidence_ids");statement.pop("parent_claim_ids")
        statement["additional_evidence_support"] = {key:False for key in choices["evidence"]}
        statement["additional_parent_support"] = {key:False for key in choices["parents"]}
    return payload


def test_confirmed_v2_duplicate_shape_is_rejected_without_repair(invocation):
    calls = []
    async def model(**kwargs):
        calls.append(True)
        payload = wire_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        for index in (6, 9, 13):
            selected = payload["outputs"][index]["strategic_parent_id"]
            payload["outputs"][index]["parent_claim_ids"] = [selected, selected]
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True).execute(invocation))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID and calls == [True]


@pytest.mark.parametrize("projection", [False, True])
def test_v3_typed_counterpart_passes_original_pipeline_and_gates(invocation, projection):
    calls = []
    async def model(**kwargs):
        calls.append(deepcopy(kwargs))
        data = json.loads(kwargs["text"])
        payload = typed_payload(data, kwargs["response_schema"])
        choices = data["experiments_support_selection_catalog"]
        for statement in payload["outputs"]:
            # An explicit overlap names one set member; no raw array exists.
            alias = next(key for key,value in choices["parents"].items()
                         if value == statement["strategic_parent_id"])
            statement["additional_parent_support"][alias] = True
            extra = next(key for key,value in choices["parents"].items()
                         if value == "clm_z_additional_recommendation")
            statement["additional_parent_support"][extra] = True
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    result = asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
        support_selection_wire=True, provider_schema_projection=projection).execute(invocation))
    quality = evaluate_result(invocation.execution_id, result, invocation.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    for statement in result.payload["outputs"]:
        assert "clm_z_additional_recommendation" in statement["parent_claim_ids"]
        assert len(statement["parent_claim_ids"]) == len(set(statement["parent_claim_ids"]))
        assert "additional_parent_support" not in statement
    assert result_from_json(result_to_json(result)) == result
    assert result.schema_version == "experiments.payload.v1" and "wire_contract_version" not in result.payload
    assert len(calls) == 1


@pytest.mark.parametrize("mutation", [
    lambda p,s: p.update(wire_contract_version="unknown"),
    lambda p,s: s.update(parent_claim_ids=[s["strategic_parent_id"]] * 2),
    lambda p,s: s.update(evidence_ids=[]),
    lambda p,s: s.pop("additional_parent_support"),
    lambda p,s: s["additional_parent_support"].pop("p000"),
    lambda p,s: s["additional_parent_support"].update(p999=True),
    lambda p,s: s["additional_parent_support"].update(p000=1),
    lambda p,s: s["additional_parent_support"].update(p000="true"),
    lambda p,s: s.update(additional_parent_support=[]),
    lambda p,s: s["additional_evidence_support"].pop("e000"),
    lambda p,s: s["additional_evidence_support"].update(e999=True),
    lambda p,s: s["additional_evidence_support"].update(e000=1),
    lambda p,s: s.update(strategic_parent_id="clm_unknown"),
    lambda p,s: s.update(strategic_parent_id="clm_z_additional_recommendation"),
    lambda p,s: s.update(strategic_parent_id=None),
    lambda p,s: s.update(text=""),
    lambda p,s: p["experiments"][0].update(related_strategic_claim_ids=[]),
    lambda p,s: p["experiments"][0].update(time_resource_constraints=["Invented budget"]),
])
def test_malformed_selections_and_legacy_arrays_are_not_repaired(invocation, mutation):
    calls = []
    async def model(**kwargs):
        calls.append(True)
        payload = typed_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        mutation(payload, payload["outputs"][6])
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(invocation))
    assert calls == [True]


@pytest.mark.parametrize("projection", [False, True])
def test_flag_off_preserves_v2_model_arguments_and_instruction_bytes(invocation, projection):
    calls = []
    async def model(**kwargs):
        calls.append(deepcopy(kwargs))
        return json.dumps(wire_payload(json.loads(kwargs["text"]), kwargs["response_schema"]))
    first = asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
        provider_schema_projection=projection).execute(invocation))
    second = asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
        support_selection_wire=False, provider_schema_projection=projection).execute(invocation))
    assert calls[0] == calls[1] and result_to_json(first) == result_to_json(second)
    assert "experiments_support_selection_catalog" not in json.loads(calls[0]["text"])
    assert WIRE_VERSION not in calls[0]["instruction"]
    assert wire_version(calls[0]["response_schema"]) == "experiments.wire.v2"
    assert WIRE_VERSION not in ExperimentsExecutor.instruction


def wire_version(schema):
    return schema["properties"]["wire_contract_version"]["enum"][0]


@pytest.mark.parametrize("flag", [None, 1, "true"])
def test_constructor_requires_boolean(flag):
    with pytest.raises(TypeError):
        ExperimentsExecutor(model_call=AsyncMock(), strategic_parent_wire=True, support_selection_wire=flag)


def test_v3_requires_strategic_parent_wire():
    with pytest.raises(ValueError, match="requires strategic parent wire"):
        ExperimentsExecutor(model_call=AsyncMock(), support_selection_wire=True)


@pytest.mark.parametrize("strategic", [False, True])
@pytest.mark.parametrize("selection", [False, True])
@pytest.mark.parametrize("projection", [False, True])
def test_default_off_registry_and_composition_wiring(monkeypatch, strategic, selection, projection):
    from app.orchestration_runtime.composition import build_production_graph_runtime
    from tests.test_module_executors import analyzer
    from tests.test_production_graph_worker import queue
    monkeypatch.setattr(settings, "EXPERIMENTS_STRATEGIC_PARENT_WIRE_ENABLED", strategic)
    monkeypatch.setattr(settings, "EXPERIMENTS_SUPPORT_SELECTION_WIRE_ENABLED", selection)
    monkeypatch.setattr(settings, "EXPERIMENTS_SCHEMA_PROJECTION_ENABLED", projection)
    if selection and not strategic:
        with pytest.raises(ValueError):build_production_graph_runtime(queue=queue(), analyzer=analyzer())
    else:
        executor = build_production_graph_runtime(queue=queue(), analyzer=analyzer()).executors.resolve("experiments.v1")
        assert executor._support_selection_wire is selection
        assert executor._strategic_parent_wire is strategic
        assert executor._provider_schema_projection is projection
    assert Settings.model_fields["EXPERIMENTS_SUPPORT_SELECTION_WIRE_ENABLED"].default is False


def scope_schema(evidence_count, parent_count):
    from app.module_execution.executors.intelligence_schemas import ExperimentsOutput
    from app.module_execution.executors.support_schema import support_response_schema, SupportRequirement
    from app.module_execution.executors.experiments_support_wire import strategic_parent_wire_schema
    evidence = [f"evd_scope_{i:03d}" for i in range(evidence_count)]
    parents = [f"clm_scope_{i:03d}" for i in range(parent_count)]
    canonical = support_response_schema(ExperimentsOutput, evidence, parents,
        requirement=SupportRequirement.PARENT_REQUIRED)
    return strategic_parent_wire_schema(canonical, parents[:1]), evidence, parents


def test_full_250_source_families_with_one_output_and_2048_boolean_boundary():
    from app.module_execution.errors import ModuleExecutionContractError
    from app.module_execution.executors.experiments_support_selection import (
        support_selection_wire_schema, support_selection_catalog, MAX_REQUIRED_BOOLEAN_FLAGS,
    )
    v2, evidence, parents = scope_schema(250, 250)
    before = deepcopy(v2)
    v3 = support_selection_wire_schema(v2, 1, evidence, parents)
    for name in ("ExperimentsAdditionalEvidenceSupport", "ExperimentsAdditionalParentSupport"):
        definition = v3["$defs"][name]
        assert len(definition["properties"]) == len(definition["required"]) == 250
        assert definition["additionalProperties"] is False
    assert v2 == before
    with pytest.raises(ModuleExecutionContractError):support_selection_wire_schema(v2, 16, evidence, parents)
    with pytest.raises(ModuleExecutionContractError):support_selection_catalog([f"evd_{i}" for i in range(251)], parents)
    with pytest.raises(ModuleExecutionContractError):support_selection_catalog(evidence, [f"clm_{i}" for i in range(251)])
    v2, evidence, parents = scope_schema(64, 64)
    assert 16 * (len(evidence) + len(parents)) == MAX_REQUIRED_BOOLEAN_FLAGS
    support_selection_wire_schema(v2, 16, evidence, parents)
    v2, evidence, parents = scope_schema(65, 64)
    with pytest.raises(ModuleExecutionContractError):support_selection_wire_schema(v2, 16, evidence, parents)


def test_generation_overhead_refuses_before_model_without_filtering_sources(invocation):
    from tests.test_module_executors import fact
    from app.module_execution.errors import ModuleExecutionContractError
    request = replace(invocation, context_packet=replace(invocation.context_packet,
        known_facts=tuple(fact(f"support_selection_{i}", "Qualitative supplied context") for i in range(129))))
    model = AsyncMock()
    with pytest.raises(ModuleExecutionContractError):
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(request))
    model.assert_not_called()


def test_v3_preserves_content_contracts_and_caller_schema_without_mutation():
    from app.module_execution.executors.experiments_support_selection import support_selection_wire_schema
    v2, evidence, parents = scope_schema(2, 3)
    before = deepcopy(v2)
    v3 = support_selection_wire_schema(v2, 16, evidence, parents)
    assert v2 == before
    assert v3["$defs"]["ExperimentDesign"] == v2["$defs"]["ExperimentDesign"]
    old = v2["$defs"]["ExperimentStatement"]["properties"]
    assert v3["$defs"]["ExperimentStatement"] == {"anyOf": [
        {"$ref": "#/$defs/" + EVIDENCE_BASIS_DEFINITION},
        {"$ref": "#/$defs/" + OTHER_STATEMENT_DEFINITION},
    ]}
    new = v3["$defs"][OTHER_STATEMENT_DEFINITION]["properties"]
    for key in ("text", "kind", "confidence", "strategic_parent_id"):
        assert new[key] == old[key]
    assert new["output_name"] == {**old["output_name"],
        "enum": [name for name in old["output_name"]["enum"] if name != "evidence_basis"]}
    basis = v3["$defs"][EVIDENCE_BASIS_DEFINITION]["properties"]
    assert basis["output_name"]["enum"] == ["evidence_basis"]
    assert basis["text"]["enum"] == list(EVIDENCE_BASIS_NOTES)
    assert basis["text"]["minLength"] == old["text"]["minLength"] == 1
    assert basis["text"]["maxLength"] == old["text"]["maxLength"] == 4000
    for key in set(basis) - {"output_name", "text"}:
        assert basis[key] == new[key]
    assert "parent_claim_ids" not in new and "evidence_ids" not in new
    from app.module_execution.executors.provider_schema import nodes
    for node in nodes(v3):
        if "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


@pytest.mark.parametrize("note", EVIDENCE_BASIS_NOTES)
def test_evidence_basis_note_preserves_exact_selections_and_canonical_history(invocation, note):
    captured = {}
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        payload = typed_payload(data, kwargs["response_schema"])
        basis = next(row for row in payload["outputs"] if row["output_name"] == "evidence_basis")
        basis["text"] = note
        for family in ("evidence", "parents"):
            mapping = data["experiments_support_selection_catalog"][family]
            field = "additional_evidence_support" if family == "evidence" else "additional_parent_support"
            if mapping:
                alias = next(iter(mapping))
                basis[field][alias] = True
                captured[family] = mapping[alias]
        captured["primary"] = basis["strategic_parent_id"]
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    result = asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
        support_selection_wire=True).execute(invocation))
    basis = next(row for row in result.payload["outputs"] if row["output_name"] == "evidence_basis")
    assert basis["text"] == note
    assert basis["evidence_ids"] == (captured["evidence"],)
    assert set(basis["parent_claim_ids"]) == {captured["parents"], captured["primary"]}
    quality = evaluate_result(invocation.execution_id, result, invocation.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    assert result_from_json(result_to_json(result)) == result


@pytest.mark.parametrize("text", [
    "Поддержка гипотезы базируется на позиционировании и на существующем демонстрационном образце, который показывает сравнение снимков.",
    "The existing demonstration proves the course is effective.",
    "The hypothesis is proven effective.", "", "x" * 4001,
])
def test_evidence_basis_cannot_generate_mixed_proof_prose_or_false_effectiveness(invocation, text):
    calls = []
    async def model(**kwargs):
        calls.append(True)
        payload = typed_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        next(row for row in payload["outputs"] if row["output_name"] == "evidence_basis")["text"] = text
        assert not Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(invocation))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID and calls == [True]


@pytest.mark.parametrize("mutation", ["duplicate", "missing"])
def test_evidence_basis_branches_do_not_weaken_exact_output_coverage(invocation, mutation):
    async def model(**kwargs):
        payload = typed_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        basis = next(row for row in payload["outputs"] if row["output_name"] == "evidence_basis")
        if mutation == "duplicate":
            payload["outputs"][0] = deepcopy(basis)
        else:
            payload["outputs"].remove(basis)
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(invocation))
    if mutation == "duplicate":
        assert caught.value.stage is OutputFailureStage.RESULT_CONTRACT_INVALID
        assert caught.value.failure_rule.value == "output_duplicate_names"
    else:
        assert caught.value.stage is OutputFailureStage.OUTPUT_COVERAGE_INVALID


def test_fifteen_other_output_names_retain_free_bounded_text():
    from app.module_execution.executors.experiments_support_selection import support_selection_wire_schema
    v2, evidence, parents = scope_schema(2, 3)
    wire = support_selection_wire_schema(v2, 16, evidence, parents)
    definition = wire["$defs"][OTHER_STATEMENT_DEFINITION]
    validator = Draft202012Validator({"$defs": wire["$defs"], **definition})
    names = definition["properties"]["output_name"]["enum"]
    assert len(names) == 15 and "evidence_basis" not in names
    for name in names:
        statement = {"output_name": name, "text": "Compare supplied alternatives",
            "kind": "HYPOTHESIS", "confidence": "MEDIUM", "strategic_parent_id": parents[0],
            "additional_evidence_support": {"e000": False, "e001": False},
            "additional_parent_support": {"p000": False, "p001": False, "p002": False}}
        assert validator.is_valid(statement), name
        assert validator.is_valid({**statement, "text": "x" * 4000}), name
        for text in ("", "x" * 4001, "Compare 2 options"):
            assert not validator.is_valid({**statement, "text": text}), (name, text[:20])


@pytest.mark.parametrize("mutation", ["basis_collision", "other_collision", "output_names", "text_bound", "array_ref"])
def test_evidence_basis_specialization_refuses_unknown_contracts_without_mutating(mutation):
    from app.module_execution.errors import ModuleExecutionContractError
    from app.module_execution.executors.experiments_support_selection import support_selection_wire_schema
    v2, evidence, parents = scope_schema(2, 3)
    if mutation == "basis_collision":
        v2["$defs"][EVIDENCE_BASIS_DEFINITION] = {"type": "string"}
    elif mutation == "other_collision":
        v2["$defs"][OTHER_STATEMENT_DEFINITION] = {"type": "string"}
    elif mutation == "output_names":
        v2["$defs"]["ExperimentStatement"]["properties"]["output_name"]["enum"].append("unknown")
    elif mutation == "text_bound":
        v2["$defs"]["ExperimentStatement"]["properties"]["text"]["maxLength"] = 4001
    else:
        v2["properties"]["outputs"]["items"] = {"type": "object"}
    before = deepcopy(v2)
    with pytest.raises(ModuleExecutionContractError):
        support_selection_wire_schema(v2, 16, evidence, parents)
    assert v2 == before


def test_complete_budget_collision_reference_and_scope_guards():
    from app.module_execution.errors import ModuleExecutionContractError
    from app.module_execution.executors.experiments_support_selection import support_selection_wire_schema
    v2, evidence, parents = scope_schema(2, 3)
    for mutation in (lambda s:s["$defs"].update(ExperimentsAdditionalParentSupport={"type":"object"}),
                     lambda s:s["$defs"]["ExperimentStatement"]["properties"].update(strategic_parent_id={"$ref":"https://invalid/"}),
                     lambda s:s["$defs"]["AllowedEvidenceId"].update(enum=["evd_unknown"])):
        changed = deepcopy(v2);mutation(changed);before = deepcopy(changed)
        with pytest.raises(ModuleExecutionContractError):support_selection_wire_schema(changed, 16, evidence, parents)
        assert changed == before
    # Start from a V2 that fits exactly within the shared string budget. New map
    # definitions/aliases must trigger the post-construction guard, not bypass it.
    from app.module_execution.executors.support_schema import check_schema_bounds, MAX_SCHEMA_STRING_CHARACTERS
    v2["$defs"]["Budget"] = {"type":"string", "enum":[""]}
    low, high = 0, MAX_SCHEMA_STRING_CHARACTERS
    while low < high:
        middle = (low + high + 1) // 2
        v2["$defs"]["Budget"]["enum"] = ["x" * middle]
        try:check_schema_bounds(v2)
        except ModuleExecutionContractError:high = middle - 1
        else:low = middle
    v2["$defs"]["Budget"]["enum"] = ["x" * low]
    check_schema_bounds(v2)
    with pytest.raises(ModuleExecutionContractError):support_selection_wire_schema(v2, 1, evidence, parents)
    # An already over-budget enum input must also be rejected, never pruned.
    v2, evidence, parents = scope_schema(2, 3)
    v2["$defs"]["Budget"] = {"type":"string", "enum":[str(i) for i in range(1001)]}
    with pytest.raises(ModuleExecutionContractError):support_selection_wire_schema(v2, 1, evidence, parents)



@pytest.mark.parametrize("cite", [False, True])
@pytest.mark.parametrize("projection", [False, True])
def test_numeric_assertion_requires_its_actual_selected_support(invocation, cite, projection):
    quote = "Supplied scenario contains 20 qualified inquiries"
    parent_id = "clm_z_additional_recommendation"
    request = replace_parent_assertion(invocation, parent_id, quote)
    async def model(**kwargs):
        data = json.loads(kwargs["text"]);payload = typed_payload(data, kwargs["response_schema"])
        payload["outputs"][2]["text"] = quote
        alias = next(key for key,value in data["experiments_support_selection_catalog"]["parents"].items() if value == parent_id)
        payload["outputs"][2]["additional_parent_support"][alias] = cite
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    executor = ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
        support_selection_wire=True, provider_schema_projection=projection)
    if cite:
        result = asyncio.run(executor.execute(request));assert result.payload["outputs"][2]["text"] == quote
    else:
        with pytest.raises(ExecutorOutputError) as caught:asyncio.run(executor.execute(request))
        assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_context_only_parent_quotes_do_not_gain_assertion_authority(invocation):
    quote = "Supplied 37 qualified inquiries"
    value = json.dumps({"summary":"Qualitative summary", "items":["Validate the message"],
        "numeric_context":[{"support_id":"evd_context", "quote":quote, "attribution":"supplied_context"}]})
    request = replace_parent_assertion(invocation, "clm_z_additional_recommendation", value)
    async def model(**kwargs):
        payload = typed_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        payload["outputs"][2]["text"] = quote
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(request))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_thirty_three_selected_sources_fail_canonical_bound_without_truncation(invocation):
    from tests.test_module_executors import fact
    request = replace(invocation, context_packet=replace(invocation.context_packet,
        known_facts=tuple(fact(f"selected_{i}", "Supplied qualitative context") for i in range(33))))
    calls = []
    async def model(**kwargs):
        calls.append(True)
        data = json.loads(kwargs["text"]);payload = typed_payload(data, kwargs["response_schema"])
        payload["outputs"][2]["additional_evidence_support"] = {key:True for key in data["experiments_support_selection_catalog"]["evidence"]}
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(request))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID and calls == [True]


@pytest.mark.parametrize("duplicate_json", [False, True])
def test_actual_http_adapter_one_attempt_and_duplicate_json_rejection(monkeypatch, invocation, duplicate_json):
    import httpx
    from tests.test_graph_model_adapter import install_transport
    from app.orchestration_runtime.model_adapter import production_model_call
    from app.orchestration_runtime.worker import transient
    calls = []
    def response(wire):
        body = json.loads(wire.content);calls.append(body)
        data = json.loads(body["input"][1]["content"])
        payload = typed_payload(data, body["text"]["format"]["schema"])
        raw = json.dumps(payload)
        if duplicate_json:raw = raw.replace('"p000": false', '"p000": false, "p000": true', 1)
        return httpx.Response(200, json={"status":"completed", "output_text":raw})
    install_transport(monkeypatch, response)
    executor = ExperimentsExecutor(model_call=production_model_call, strategic_parent_wire=True,
        support_selection_wire=True, provider_schema_projection=True)
    if duplicate_json:
        with pytest.raises(ExecutorOutputError) as caught:asyncio.run(executor.execute(invocation))
        assert caught.value.stage is OutputFailureStage.JSON_INVALID and not transient(caught.value)
    else:
        result = asyncio.run(executor.execute(invocation))
        quality = evaluate_result(invocation.execution_id, result, invocation.upstream_results)
        assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    assert len(calls) == 1 and calls[0]["max_output_tokens"] == 16000


def test_provider_cannot_mutate_original_wire_validator(invocation):
    async def model(**kwargs):
        payload = typed_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        kwargs["response_schema"].clear()
        payload["outputs"][0]["text"] = ""
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(invocation))



def test_decoder_preserves_model_text_and_does_not_mutate_wire_payload(invocation):
    from app.module_execution.executors.experiments_support_selection import decode_support_selection_wire
    # The production executor captures the exact V2 contract while constructing V3.
    captured = {}
    class Capture(ExperimentsExecutor):
        def _v2_wire_schema(self, request, canonical, evidence):
            wire = super()._v2_wire_schema(request, canonical, evidence)
            captured["v2"] = deepcopy(wire)
            captured["evidence"] = tuple(e.record.evidence_id for e in evidence)
            from app.module_execution.executors.common import parent_claims
            captured["parents"] = tuple(parent_claims(request))
            return wire
    async def model(**kwargs):
        data = json.loads(kwargs["text"]);payload = typed_payload(data, kwargs["response_schema"])
        before = deepcopy(payload)
        decoded = decode_support_selection_wire(payload, captured["v2"], len(invocation.expected_outputs),
            captured["evidence"], captured["parents"])
        assert payload == before
        assert [s["text"] for s in decoded["outputs"]] == [s["text"] for s in payload["outputs"]]
        assert decoded["experiments"] == payload["experiments"]
        return json.dumps(payload)
    asyncio.run(Capture(model_call=model, strategic_parent_wire=True, support_selection_wire=True).execute(invocation))


def test_noncompliant_provider_cannot_bypass_original_selected_parent_or_number_rules(invocation):
    # V3 exposes explicit selections; it does not infer a citation from a quoted
    # request-wide assertion or change qualitative word-quantity acceptance.
    async def model(**kwargs):
        payload = typed_payload(json.loads(kwargs["text"]), kwargs["response_schema"])
        payload["outputs"][2]["text"] = "Ask three questions about the offer"
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(invocation))
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID



@pytest.mark.parametrize("shape", ["allOf", "not", "if", "contains", "array_items", "array_not"])
def test_unknown_statement_or_support_array_shape_refuses_before_model(monkeypatch, invocation, shape):
    from app.module_execution.errors import ModuleExecutionContractError
    from app.module_execution.executors.experiments_support_selection import support_selection_wire_schema
    def corrupt(schema):
        node = schema["$defs"]["ExperimentStatement"]
        if shape in ("allOf", "not", "if", "contains"):
            node[shape] = [{"required":["parent_claim_ids"]}] if shape == "allOf" else {"required":["parent_claim_ids"]}
        elif shape == "array_items":
            node["properties"]["parent_claim_ids"]["items"] = {"anyOf":[{"$ref":"#/$defs/AllowedParentClaimId"}]}
        else:node["properties"]["parent_claim_ids"]["not"] = {"maxItems":0}
    v2, evidence, parents = scope_schema(2, 3)
    corrupt(v2);before = deepcopy(v2)
    with pytest.raises(ModuleExecutionContractError):support_selection_wire_schema(v2, 16, evidence, parents)
    assert v2 == before
    original = ExperimentsExecutor._v2_wire_schema
    def changed(self, request, canonical, local):
        schema = original(self, request, canonical, local)
        corrupt(schema)
        return schema
    monkeypatch.setattr(ExperimentsExecutor, "_v2_wire_schema", changed)
    model = AsyncMock()
    with pytest.raises(ModuleExecutionContractError):
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(invocation))
    model.assert_not_called()



def test_empty_local_family_is_closed_and_valid_with_primary_parent(invocation):
    request = replace(invocation, context_packet=replace(invocation.context_packet,
        known_facts=(), relevant_project_context=(), constraints=()))
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        assert data["experiments_support_selection_catalog"]["evidence"] == {}
        definition = kwargs["response_schema"]["$defs"]["ExperimentsAdditionalEvidenceSupport"]
        assert definition == {"type":"object", "properties":{}, "required":[], "additionalProperties":False}
        return json.dumps(typed_payload(data, kwargs["response_schema"]))
    result = asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
        support_selection_wire=True).execute(request))
    assert all(not statement["evidence_ids"] and statement["parent_claim_ids"] for statement in result.payload["outputs"])
    quality = evaluate_result(request.execution_id, result, request.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])


def test_thirty_three_selected_parents_also_fail_canonical_bound_without_truncation(invocation):
    from app.module_execution.executors.common import plain
    upstream = invocation.upstream_results[0]
    parent = next(c for c in upstream.result.normalized_result.claims if c.claim_type.value == "HYPOTHESIS")
    clones = tuple(replace(parent, claim_id=f"clm_selected_parent_{i}") for i in range(34))
    expanded = replace(upstream, result=replace(upstream.result, payload=plain(upstream.result.payload),
        normalized_result=replace(upstream.result.normalized_result, claims=clones)))
    request = replace(invocation, upstream_results=tuple(expanded if u is upstream else u for u in invocation.upstream_results))
    calls = []
    async def model(**kwargs):
        calls.append(True)
        data = json.loads(kwargs["text"]);payload = typed_payload(data, kwargs["response_schema"])
        selected = payload["outputs"][2]["strategic_parent_id"]
        choices = data["experiments_support_selection_catalog"]["parents"]
        aliases = [key for key,value in choices.items() if value != selected][:32]
        assert len(aliases) == 32
        for key in aliases:payload["outputs"][2]["additional_parent_support"][key] = True
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
            support_selection_wire=True).execute(request))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID and calls == [True]
