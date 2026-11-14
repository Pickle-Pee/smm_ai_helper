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
from app.module_execution.executors.cmo_demo_plans import DEMO_FREE_PATTERN, DEMO_ITEMS_NOTE, DEMO_PLAN_NOTES
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
from app.module_execution.executors.cmo_source_selection import (
    source_selection_catalog, validate_source_catalog, source_text_schema, render_source_leaf,
    SOURCE_ITEMS_DESCRIPTION,
)
from app.module_execution.executors.common import EvidenceSourceClass
from app.module_execution.executors.downstream_fidelity import typed_literal_sources, selected_sources
from types import SimpleNamespace
import httpx

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
    assert {key: value for key, value in items.items() if key not in {"items", "description"}} == {
        key: value for key, value in other["properties"]["items"].items() if key not in {"items", "description"}}
    assert other["properties"]["items"]["description"].endswith(DEMO_ITEMS_NOTE)
    assert items["minItems"] == 1 and items["maxItems"] == 3
    assert items["items"]["enum"] == list(TRADEOFF_ITEM_NOTES)
    assert items["items"]["minLength"] == 1 and items["items"]["maxLength"] == 300
    assert trade["properties"]["text"]["pattern"] == DEMO_FREE_PATTERN
    assert schema["properties"]["outputs"]["properties"]["trade_offs"] == {"$ref": "#/$defs/" + TRADEOFFS_DEFINITION}
    # v13: every free CMO prose branch uses the demo-free variant of the qualitative pattern.
    assert all(node["pattern"] == DEMO_FREE_PATTERN for node in nodes(schema) if "pattern" in node)
    assert "pattern" not in schema["properties"]["limitations"]["items"]
    assert canonical == contracts(req)[0]


@pytest.mark.parametrize("note", TRADEOFF_ITEM_NOTES)
def test_every_closed_tradeoff_policy_passes_normal_executor_and_quality(note):
    assert 1 <= len(note) <= 300 and not has_numeric_quantity(note)
    req = scoped_request()
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        payload = wire_output(req.expected_outputs, data["support_selection_catalog"], data.get("cmo_source_selection_catalog"))
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
        payload = wire_output(req.expected_outputs, aliases, data.get("cmo_source_selection_catalog"))
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
            payload = wire_output(req.expected_outputs, data["support_selection_catalog"], data.get("cmo_source_selection_catalog"))
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


DEMO_SOURCE = "Демонстрационный образец показывает сравнение снимков."


def source_request(role="existing_proof", text=DEMO_SOURCE, names=None):
    req = scoped_request(outputs=names)
    facts = req.context_packet.known_facts
    if any(item.label == role for item in facts):
        facts = tuple(replace(item, value=text) if item.label == role else item for item in facts)
    else:
        facts = (*facts, fact(role, text))
    return replace(req, context_packet=replace(req.context_packet,
        known_facts=facts))


def source_contracts(req):
    canonical, schema, ids, parents, numeric = contracts(req)
    evidence = first_party_evidence(req, scoped_facts(req))
    choices = source_selection_catalog(evidence, support_selection_catalog(ids, parents)["evidence"])
    return canonical, schema, ids, parents, numeric, choices


@pytest.mark.parametrize("field", ["text", "items"])
@pytest.mark.parametrize("role,text", [("existing_proof", DEMO_SOURCE),
    ("product_truth", OWNER), ("confirmed_business_fact", OWNER),
    ("confirmed_business_fact", "Курс  включает стандартизированную\nписьменную обратную связь.")])
def test_explicit_source_choice_alone_renders_whole_source_selects_id_same_output_and_passes_qg(field, role, text):
    name = "strategic_priorities" if role == "existing_proof" else "strategic_diagnosis"
    req = source_request(role, text, names=(name, "resource_priorities"))
    observed = []
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        choices = data["cmo_source_selection_catalog"]
        marker = next(key for key, row in choices.items() if row["input_key"] == role)
        payload = wire_output(req.expected_outputs, data["support_selection_catalog"], data.get("cmo_source_selection_catalog"))
        row = payload["outputs"][name]
        row[field] = marker if field == "text" else [marker]
        assert not any(row["additional_evidence_support"].values())
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        observed.append((deepcopy(payload), choices[marker]["evidence_id"]))
        return json.dumps(payload)
    result = asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
    row = next(row for row in result.payload["outputs"] if row["output_name"] == name)
    assert row[field] == (text if field == "text" else (text,))
    assert observed[0][1] in row["evidence_ids"]
    assert all(observed[0][1] not in other["evidence_ids"] for other in result.payload["outputs"] if other["output_name"] != name)
    assert not any(observed[0][0]["outputs"][name]["additional_evidence_support"].values())
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    assert result_from_json(result_to_json(result)) == result


@pytest.mark.parametrize("prose", [DEMO_SOURCE, DEMO_SOURCE[:-1] + " и может служить иллюстрацией акцента."])
def test_ordinary_demo_prose_stays_unrepaired_and_source_in_another_output_does_not_authorize_it(prose):
    req = source_request()
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        marker = next(iter(data["cmo_source_selection_catalog"]))
        payload = wire_output(req.expected_outputs, data["support_selection_catalog"], data.get("cmo_source_selection_catalog"))
        payload["outputs"]["strategic_priorities"]["items"] = [prose]
        payload["outputs"]["strategic_bets"]["text"] = marker
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
    # v13 rejects free demo prose already at the wire schema (stricter than v12 semantics).
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_demo_source_selection_does_not_grant_owner_product_authority():
    req = source_request("existing_proof", OWNER)
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        payload = wire_output(req.expected_outputs, data["support_selection_catalog"], data.get("cmo_source_selection_catalog"))
        payload["outputs"]["strategic_priorities"]["text"] = next(iter(data["cmo_source_selection_catalog"]))
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


@pytest.mark.parametrize("where", ["risks.text", "risks.items", "trade_offs.items", "assumptions", "limitations"])
def test_closed_or_global_locations_never_render_or_leak_reserved_markers(where):
    req = source_request()
    canonical, _, ids, parents, numeric, choices = source_contracts(req)
    value = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    marker = next(iter(choices))
    if "." in where:
        name, field = where.split(".")
        value["outputs"][name][field] = marker if field == "text" else [marker]
    else:
        value[where] = [marker]
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, choices)


@pytest.mark.parametrize("text", ["SOURCE:e999", "SOURCE:p000", "source:e000", "SOURCE:unknown",
    "SOURCE:e000 plus interpretation", "Prefix SOURCE:e000", "SOURCE:", "Source:unknown",
    "prefixSOURCE:e000suffix", "Resource:e000", "xsource:e000y"])
def test_unknown_malformed_concatenated_namespace_is_never_literal_fallback(text):
    req = source_request(names=("strategic_priorities",))
    canonical, _, ids, parents, numeric, choices = source_contracts(req)
    value = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    value["outputs"]["strategic_priorities"]["text"] = text
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, choices)


def test_partial_scope_field_sizes_no_recursive_source_and_original_schema_shapes():
    req = source_request(text="Owner condition " + "x" * 300, role="confirmed_business_fact", names=("trade_offs", "strategic_diagnosis"))
    canonical, schema, ids, parents, numeric, choices = source_contracts(req)
    marker = next(iter(choices))
    value = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    value["outputs"]["trade_offs"]["text"] = marker
    assert Draft202012Validator(schema).is_valid(value)
    decoded = decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, choices)
    assert decoded["outputs"][0]["text"] == choices[marker]["text"]
    value["outputs"]["strategic_diagnosis"]["items"] = [marker]
    assert not Draft202012Validator(schema).is_valid(value)
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(value, canonical, req.expected_outputs, ids, parents, numeric, choices)
    field = {"type": "string", "minLength": 1, "maxLength": 300, "pattern": QUALITATIVE_GENERATION_PATTERN}
    assert source_text_schema(field, 300, choices) == field
    with pytest.raises(ModuleExecutionContractError):
        source_text_schema({**field, "unknown": True}, 300, {})


def fake_source(identity, text, role="product_truth", source_class=EvidenceSourceClass.FIRST_PARTY):
    return SimpleNamespace(record=SimpleNamespace(evidence_id=identity, source_class=source_class), value=text, input_key=role)


def test_catalog_eligibility_uses_same_canonical_role_function_with_extra_generation_bounds():
    foreign = next(value for value in EvidenceSourceClass if value is not EvidenceSourceClass.FIRST_PARTY)
    rows = [fake_source("owner", OWNER), fake_source("demo", DEMO_SOURCE, "existing_proof"),
        fake_source("confirmed", OWNER, "confirmed_business_fact"), fake_source("audience", OWNER, "target_audience"),
        fake_source("foreign", OWNER, source_class=foreign), fake_source("numeric", "Price is 20 dollars."),
        fake_source("structured", {"text": OWNER}), fake_source("empty", "   "),
        fake_source("long", "x" * 4001), fake_source("reserved", "This is SOURCE:another literal")]
    aliases = support_selection_catalog((row.record.evidence_id for row in rows), ())["evidence"]
    choices = source_selection_catalog(iter(rows), aliases)
    assert {row["evidence_id"] for row in choices.values()} == {"owner", "demo", "confirmed"}
    local = {row.record.evidence_id: row for row in rows}
    for row in rows:
        identity = row.record.evidence_id
        statement = SimpleNamespace(evidence_ids=(identity,))
        assert selected_sources(statement, local) == typed_literal_sources((identity,), local)
    # Existing canonical Pydantic strips outer whitespace: omit, never trim a
    # source that cannot survive as a complete byte-exact accepted value.
    assert source_selection_catalog([fake_source("padded", "  " + OWNER + "  ")], {"e000": "padded"}) == {}


@pytest.mark.parametrize("failure", ["duplicate_id", "wrong_scope", "count_cap", "byte_cap"])
def test_catalog_scope_collision_and_byte_count_caps_fail_without_truncation(failure):
    if failure == "duplicate_id":
        rows, aliases = [fake_source("same", OWNER), fake_source("same", DEMO_SOURCE)], {"e000": "same"}
    elif failure == "wrong_scope":
        rows, aliases = [fake_source("actual", OWNER)], {"e000": "other"}
    elif failure == "count_cap":
        rows = [fake_source(f"id_{i}", OWNER) for i in range(65)]
        aliases = support_selection_catalog((row.record.evidence_id for row in rows), ())["evidence"]
    else:
        rows = [fake_source(f"id_{i}", "x" * 3900) for i in range(5)]
        aliases = support_selection_catalog((row.record.evidence_id for row in rows), ())["evidence"]
    with pytest.raises(ModuleExecutionContractError):
        source_selection_catalog(rows, aliases)


def test_unrecognized_or_numeric_or_reserved_catalog_rows_fail_validation():
    choices = source_selection_catalog([fake_source("owner", OWNER)], {"e000": "owner"})
    for update in ({"evidence_id": "different"}, {"input_key": "target_audience"},
                   {"text": "Price is 2 dollars."}, {"text": "SOURCE:again"},
                   {"text": "  " + OWNER + "  "}, {"text": "We teach two principles."},
                   {"text": "Studio Two offers practice."}, {"extra": True}):
        malformed = deepcopy(choices)
        malformed["SOURCE:e000"].update(update)
        with pytest.raises(ModuleExecutionContractError):
            validate_source_catalog(malformed, {"e000": "owner"})


def test_numeric_owner_source_remains_only_numeric_context_and_selectors_preserve_empty_catalog():
    req = source_request("product_truth", "There are two versions of the course.")
    _, schema, ids, parents, numeric, choices = source_contracts(req)
    assert not choices
    assert "anyOf" not in schema["$defs"][STATEMENTS[0]]["properties"]["text"]
    assert any(row["exact_quote"] == "There are two versions of the course." for row in numeric)


def test_source_choice_actual_http_adapter_retains_small_prose_branch(monkeypatch):
    from tests.test_graph_model_adapter import install_transport
    from app.orchestration_runtime.model_adapter import production_model_call
    req = source_request()
    calls = []
    def respond(wire):
        body = json.loads(wire.content)
        calls.append(body)
        data = json.loads(body["input"][1]["content"])
        payload = wire_output(req.expected_outputs, data["support_selection_catalog"], data.get("cmo_source_selection_catalog"))
        payload["outputs"]["strategic_priorities"]["items"] = [next(iter(data["cmo_source_selection_catalog"]))]
        return httpx.Response(200, json={"status": "completed", "output_text": json.dumps(payload)})
    install_transport(monkeypatch, respond)
    result = asyncio.run(VirtualCMOExecutor(model_call=production_model_call, support_selection_wire=True).execute(req))
    assert len(calls) == 1
    schema = calls[0]["text"]["format"]["schema"]
    branch = schema["$defs"][STATEMENTS[0]]["properties"]["text"]["anyOf"]
    assert branch[0]["pattern"] == DEMO_FREE_PATTERN
    assert all(not re.fullmatch(DEMO_FREE_PATTERN, key) for key in branch[1]["enum"])
    main_props = schema["$defs"][STATEMENTS[0]]["properties"]
    assert "technical selectors" in main_props["text"]["description"]
    assert "Digits are permitted ONLY" in branch[1]["description"]
    assert "THIS output" in branch[1]["description"]
    assert main_props["items"]["description"].startswith(SOURCE_ITEMS_DESCRIPTION)
    assert "OR exact listed SOURCE tokens" in main_props["items"]["description"]
    assert "digits are allowed ONLY" in main_props["items"]["description"]
    for definition in ("CMORisksStatement", TRADEOFFS_DEFINITION):
        items = schema["$defs"][definition]["properties"]["items"]
        assert "anyOf" not in items["items"]
        assert items["description"] != SOURCE_ITEMS_DESCRIPTION
    assert next(row for row in result.payload["outputs"] if row["output_name"] == "strategic_priorities")["items"] == (DEMO_SOURCE,)


def test_explicit_source_union_cannot_bypass_original_selected_source_count_bound():
    req = source_request()
    extra = tuple(fact("known_business_context.source_" + str(i), "Supplied business context") for i in range(30))
    req = replace(req, context_packet=replace(req.context_packet, known_facts=(*req.context_packet.known_facts, *extra)))
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        marker, source = next(iter(data["cmo_source_selection_catalog"].items()))
        payload = wire_output(req.expected_outputs, data["support_selection_catalog"], data.get("cmo_source_selection_catalog"))
        row = payload["outputs"]["strategic_priorities"]
        row["text"] = marker
        other = [key for key in row["additional_evidence_support"] if key != source["evidence_key"]]
        assert len(other) >= 32
        for key in other[:32]:
            row["additional_evidence_support"][key] = True
        assert row["additional_evidence_support"][source["evidence_key"]] is False
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))


@pytest.mark.parametrize("text", ["Resource: prepare interviews.", "Resources: prepare interviews.",
                                  "A resource: owner description."])
def test_resource_words_are_not_reserved_namespace_in_plain_prose_or_source_literals(text):
    req = source_request("confirmed_business_fact", text, names=("strategic_diagnosis", "strategic_priorities"))
    canonical, _, ids, parents, numeric, choices = source_contracts(req)
    assert any(row["text"] == text for row in choices.values())
    payload = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    payload["outputs"]["strategic_diagnosis"]["text"] = text
    decoded = decode_support_selection_wire(payload, canonical, req.expected_outputs, ids, parents, numeric, choices)
    row = next(row for row in decoded["outputs"] if row["output_name"] == "strategic_diagnosis")
    assert row["text"] == text and not row["evidence_ids"]
    marker, source = next((key, row) for key, row in choices.items() if row["text"] == text)
    payload["outputs"]["strategic_diagnosis"]["text"] = marker
    decoded = decode_support_selection_wire(payload, canonical, req.expected_outputs, ids, parents, numeric, choices)
    row = next(row for row in decoded["outputs"] if row["output_name"] == "strategic_diagnosis")
    assert row["text"] == text and source["evidence_id"] in row["evidence_ids"]


@pytest.mark.parametrize("text", ["We teach two principles.", "Studio Two offers practice."])
def test_source_is_not_an_escape_from_existing_generation_count_word_language(text):
    assert not has_numeric_quantity(text)
    assert re.fullmatch(QUALITATIVE_GENERATION_PATTERN, text) is None
    assert source_selection_catalog([fake_source("owner", text)], {"e000": "owner"}) == {}


@pytest.mark.parametrize("source_size", [0, 300, 301])
def test_source_metadata_digit_exception_is_advertised_only_where_selectors_exist(source_size):
    req = (scoped_request() if source_size == 0 else
           source_request("confirmed_business_fact", "x" * source_size))
    _, schema, _, _, _, choices = source_contracts(req)
    text = schema["$defs"][STATEMENTS[1]]["properties"]["text"]
    items = schema["$defs"][STATEMENTS[1]]["properties"]["items"]
    assert bool(choices) == (source_size > 0)
    assert ("anyOf" in text) == (source_size > 0)
    # v13: OtherStrategyStatement items always offer closed demo plans; SOURCE branch only when eligible.
    branches = items["items"]["anyOf"]
    source_branches = [b for b in branches if "enum" in b and b["enum"] != list(DEMO_PLAN_NOTES)]
    assert bool(source_branches) == (0 < source_size <= 300)
    assert branches[-1]["enum"] == list(DEMO_PLAN_NOTES)
    assert items["description"].startswith(SOURCE_ITEMS_DESCRIPTION) == (0 < source_size <= 300)
    assert items["description"].endswith(DEMO_ITEMS_NOTE)
    assert schema["$defs"][TRADEOFFS_DEFINITION]["properties"]["items"]["description"] != SOURCE_ITEMS_DESCRIPTION
    assert "SOURCE" not in str(schema["properties"]["assumptions"])
    assert "SOURCE" not in str(schema["properties"]["limitations"])
