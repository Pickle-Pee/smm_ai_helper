"""Small prospective trade-off items; free prose keeps canonical source guards."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import re

from jsonschema import Draft202012Validator
import pytest

from app.module_execution.acceptance import fully_accepted
from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.common import (
    ExecutorOutputError, OutputFailureStage, first_party_evidence, scoped_facts,
)
from app.module_execution.executors.cmo_support_wire import (
    TRADEOFFS_DEFINITION, TRADEOFF_ITEM_NOTES, STATEMENTS, WIRE_FIELDS,
    support_selection_catalog, support_selection_wire_schema, decode_support_selection_wire,
)
from app.module_execution.executors.numeric_quantity import has_numeric_quantity
from app.module_execution.executors.provider_schema import nodes
from app.module_execution.executors.qualitative_generation import QUALITATIVE_GENERATION_PATTERN
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.marketing_orchestrator.quality_gates.contracts import ClaimType
from app.orchestration_runtime.serialization import result_to_json, result_from_json
from app.orchestration_runtime.service import evaluate_result
from tests.test_cmo_support_wire import scoped_request, contracts, wire_output
from tests.test_cmo_provider_contract import PRICE
from tests.test_module_executors import fact
from tests.test_strategy_intelligence import upstream, positioning

OWNER = "Курс включает стандартизированную письменную обратную связь."
BAD_COMPARISON = "Риск переформулировать письменную обратную связь как индивидуальный разбор вместо стандартизованной обратной связи."


def test_original_productive_pattern_is_bit_exact_and_no_terminal_restriction():
    assert len(QUALITATIVE_GENERATION_PATTERN) == 959
    assert hashlib.sha256(QUALITATIVE_GENERATION_PATTERN.encode()).hexdigest() == "8cfe49afdb10b8f2319c466edc169619c93b7bb5a01aa4f0a88400cab042103c"
    assert re.fullmatch(QUALITATIVE_GENERATION_PATTERN, "Evaluate the strategic compromise")
    assert re.fullmatch(QUALITATIVE_GENERATION_PATTERN, OWNER)
    assert not re.fullmatch(QUALITATIVE_GENERATION_PATTERN, "Compare two options")


def test_only_tradeoff_items_are_specialized_and_all_other_fields_are_identical():
    req = scoped_request()
    canonical, schema, ids, parents, numeric = contracts(req)
    trade = schema["$defs"][TRADEOFFS_DEFINITION]
    other = schema["$defs"][STATEMENTS[1]]
    assert set(trade["properties"]) == WIRE_FIELDS
    assert trade["required"] == other["required"]
    assert trade["additionalProperties"] is False
    for key, field in other["properties"].items():
        if key != "items":
            assert trade["properties"][key] == field
    items = trade["properties"]["items"]
    assert {key: value for key, value in items.items() if key != "items"} == {
        key: value for key, value in other["properties"]["items"].items() if key != "items"}
    assert items["minItems"] == 1 and items["maxItems"] == 3
    assert items["items"]["enum"] == list(TRADEOFF_ITEM_NOTES)
    assert items["items"]["minLength"] == 1 and items["items"]["maxLength"] == 300
    assert trade["properties"]["text"]["pattern"] == QUALITATIVE_GENERATION_PATTERN
    assert schema["properties"]["outputs"]["properties"]["trade_offs"] == {"$ref": "#/$defs/" + TRADEOFFS_DEFINITION}
    assert all(node["pattern"] == QUALITATIVE_GENERATION_PATTERN for node in nodes(schema) if "pattern" in node)
    assert "pattern" not in schema["properties"]["limitations"]["items"]
    assert canonical == contracts(req)[0]


@pytest.mark.parametrize("note", TRADEOFF_ITEM_NOTES)
def test_every_closed_tradeoff_policy_passes_normal_executor_and_quality(note):
    assert 1 <= len(note) <= 300 and not has_numeric_quantity(note)
    req = scoped_request()
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        payload = wire_output(req.expected_outputs, data["support_selection_catalog"])
        payload["outputs"]["trade_offs"]["text"] = "Validate the strategic compromise before selecting an emphasis"
        payload["outputs"]["trade_offs"]["items"] = [note]
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    result = asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert len(result.normalized_result.claims) == 9
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    assert result_from_json(result_to_json(result)) == result


@pytest.mark.parametrize("text", [BAD_COMPARISON, OWNER, "Use the existing approved message.", "Compare two messages."])
def test_observed_and_other_arbitrary_tradeoff_items_cannot_generate(text):
    req = scoped_request()
    _, schema, ids, parents, _ = contracts(req)
    value = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    value["outputs"]["trade_offs"]["items"] = [text]
    assert not Draft202012Validator(schema).is_valid(value)


@pytest.mark.parametrize("mode", ["selected", "unselected", "demo", "hyp_parent"])
def test_free_tradeoff_summary_requires_complete_selected_owner_not_demo_or_hypothesis(mode):
    req = scoped_request()
    if mode == "hyp_parent":
        parent = positioning()
        claims = tuple(replace(claim, value=OWNER, claim_type=ClaimType.HYPOTHESIS)
                       for claim in parent.normalized_result.claims)
        parent = replace(parent, payload=result_to_json(parent)["payload"],
                         normalized_result=replace(parent.normalized_result, claims=claims))
        req = replace(req, upstream_results=upstream(parent))
    else:
        key = "existing_proof" if mode == "demo" else "confirmed_business_fact"
        req = replace(req, context_packet=replace(req.context_packet,
            known_facts=(*req.context_packet.known_facts, fact(key, OWNER))))
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        aliases = data["support_selection_catalog"]
        payload = wire_output(req.expected_outputs, aliases)
        row = payload["outputs"]["trade_offs"]
        row["text"] = OWNER
        if mode in {"selected", "demo"}:
            identity = next(item["evidence_id"] for item in data["local_evidence"] if item["input_key"] == key)
            alias = next(alias for alias, value in aliases["evidence"].items() if value == identity)
            row["additional_evidence_support"][alias] = True
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    if mode == "selected":
        result = asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
        row = next(row for row in result.payload["outputs"] if row["output_name"] == "trade_offs")
        assert row["text"] == OWNER and row["evidence_ids"]
    else:
        with pytest.raises(ExecutorOutputError) as caught:
            asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
        assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_generator_evidence_schema_and_decode_match_tuple_without_losing_source_scope():
    req = scoped_request(outputs=("trade_offs",))
    canonical, _, ids, parents, _ = contracts(req)
    evidence = first_party_evidence(req, scoped_facts(req))
    executor = VirtualCMOExecutor(model_call=None, support_selection_wire=True)
    assert executor.wire_schema_for(req, canonical, iter(evidence)) == executor.wire_schema_for(req, canonical, evidence)
    payload = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    assert executor.decode_wire_payload(req, payload, iter(evidence)) == executor.decode_wire_payload(req, payload, evidence)


def test_summary_stays_free_but_same_bad_comparison_and_globals_still_fail_canonical():
    req = scoped_request()
    for field in ("trade_offs", "assumptions", "limitations"):
        async def model(**kwargs):
            data = json.loads(kwargs["text"])
            payload = wire_output(req.expected_outputs, data["support_selection_catalog"])
            if field == "trade_offs":
                payload["outputs"][field]["text"] = BAD_COMPARISON
                assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
            else:
                payload[field] = [OWNER]
            return json.dumps(payload)
        with pytest.raises(ExecutorOutputError):
            asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))


@pytest.mark.parametrize("names", [("trade_offs",), ("main_growth_constraint",), ("trade_offs", "strategic_bets")])
def test_partial_names_source_sets_numeric_context_and_input_mutation_are_preserved(names):
    req = scoped_request(outputs=names)
    canonical, schema, ids, parents, numeric = contracts(req)
    aliases = support_selection_catalog(ids, parents)
    value = wire_output(names, aliases)
    first = value["outputs"][names[0]]
    quote_id = next(row["support_id"] for row in numeric if row["exact_quote"] == PRICE)
    first["numeric_context"] = [{"support_id": quote_id, "quote": PRICE}]
    before = deepcopy(value)
    result = decode_support_selection_wire(value, canonical, names, ids, parents, numeric)
    assert value == before
    assert [row["output_name"] for row in result["outputs"]] == list(names)
    assert result["outputs"][0]["numeric_context"] == first["numeric_context"]
    assert quote_id in result["outputs"][0]["evidence_ids"]
    assert bool(TRADEOFFS_DEFINITION in schema["$defs"]) == ("trade_offs" in names)


@pytest.mark.parametrize("change", ["collision", "unknown_shape", "missing_items", "overflow_items", "invented_numeric_pair"])
def test_tradeoff_policy_projection_and_existing_context_bounds_fail_closed(change):
    req = scoped_request(outputs=("trade_offs",))
    canonical, schema, ids, parents, numeric = contracts(req)
    if change in {"collision", "unknown_shape"}:
        if change == "collision":
            canonical["$defs"][TRADEOFFS_DEFINITION] = {"type": "string"}
        else:
            canonical["$defs"][STATEMENTS[1]]["properties"]["items"]["unknown"] = True
        with pytest.raises(ModuleExecutionContractError):
            support_selection_wire_schema(canonical, req.expected_outputs, ids, parents, numeric)
    else:
        value = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
        row = value["outputs"]["trade_offs"]
        if change == "missing_items":
            row["items"] = []
        elif change == "overflow_items":
            row["items"] = [TRADEOFF_ITEM_NOTES[0]] * 4
        else:
            row["numeric_context"] = [{"support_id": ids[0], "quote": "Invented 2 versions."}]
        with pytest.raises(ModuleExecutionContractError):
            decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric)
