"""CMO provider constraints express existing prose and quotation boundaries."""
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from app.module_execution.executors.common import first_party_evidence, parent_claims, scoped_facts
from app.module_execution.executors.intelligence_schemas import StrategyOutput
from app.module_execution.executors.support_schema import support_response_schema
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.module_registry import ModuleId
from tests.test_module_executors import fact, request

PRICE = "Price is 20 dollars, including materials."
DURATION = "The course lasts 6 weeks, including practice."


def invocation():
    return request(ModuleId.VIRTUAL_CMO, facts=(fact("business_goal", "Validate demand"),
        fact("product", "Synthetic course"), fact("product_truth", PRICE), fact("duration", DURATION)), identity="a" * 32)


def capture(req=None):
    req = req or invocation()
    executor = VirtualCMOExecutor(model_call=None)
    evidence = first_party_evidence(req, scoped_facts(req))
    schema = support_response_schema(StrategyOutput, [e.record.evidence_id for e in evidence],
        parent_claims(req), requirement=executor.support_requirement_for(req))
    return req, schema, executor.provider_schema_for(req, schema), {e.input_key:e.record.evidence_id for e in evidence}


def output(ids, **changes):
    return {"outputs":[{"output_name":"main_growth_constraint", "text":"Validate qualified demand",
        "items":["Interview prospective customers"], "numeric_context":[], "kind":"HYPOTHESIS",
        "confidence":"MEDIUM", "evidence_ids":[ids["product_truth"]], "parent_claim_ids":[], **changes}],
        "assumptions":[], "limitations":[]}


@pytest.mark.parametrize("field", ["text", "items"])
def test_provider_rejects_digits_already_forbidden_by_cmo_guard(field):
    _, original, projected, ids = capture()
    value = output(ids, **{field:"Compare 2 options" if field == "text" else ["Compare 2 options"]})
    assert Draft202012Validator(original).is_valid(value)
    assert not Draft202012Validator(projected).is_valid(value)


def test_provider_rejects_numeric_context_for_source_without_eligible_quote():
    _, original, projected, ids = capture()
    value = output(ids, numeric_context=[{"support_id":ids["product"], "quote":PRICE}])
    assert Draft202012Validator(original).is_valid(value)
    assert not Draft202012Validator(projected).is_valid(value)


@pytest.mark.parametrize("key,quote", [("product_truth", PRICE), ("duration", DURATION)])
def test_complete_same_source_numeric_pair_remains_allowed(key, quote):
    _, original, projected, ids = capture()
    value = output(ids, numeric_context=[{"support_id":ids[key], "quote":quote}])
    assert Draft202012Validator(original).is_valid(value)
    assert Draft202012Validator(projected).is_valid(value)


@pytest.mark.parametrize("key,quote", [("product_truth", DURATION), ("duration", PRICE),
    ("product_truth", "20 dollars"), ("product_truth", PRICE.replace("20", "25")),
    ("product_truth", "x" * 1001), ("unknown", PRICE)])
def test_cross_source_fragment_changed_or_unknown_pairs_are_not_generated(key, quote):
    _, _, projected, ids = capture()
    identity = ids.get(key, "evd_unknown")
    assert not Draft202012Validator(projected).is_valid(output(ids,
        numeric_context=[{"support_id":identity, "quote":quote}]))


def test_empty_catalog_requires_empty_numeric_context_without_empty_enums():
    from app.module_execution.executors.provider_schema import nodes
    req = request(ModuleId.VIRTUAL_CMO, facts=(fact("business_goal", "Validate demand"), fact("product", "Course")))
    _, original, projected, ids = capture(req)
    ids["product_truth"] = ids["product"]
    assert Draft202012Validator(projected).is_valid(output(ids))
    for node in nodes(projected):
        assert node.get("enum") != []
        if "numeric_context" in node.get("properties", {}):
            assert node["properties"]["numeric_context"]["maxItems"] == 0
    value = output(ids, numeric_context=[{"support_id":ids["product"], "quote":PRICE}])
    assert Draft202012Validator(original).is_valid(value)
    assert not Draft202012Validator(projected).is_valid(value)


def test_original_schema_is_not_mutated_and_qualitative_pattern_is_idempotent():
    from app.module_execution.executors.cmo_provider_contract import qualitative_cmo_schema
    req, original, projected, _ = capture()
    before = deepcopy(original)
    assert VirtualCMOExecutor(model_call=None).provider_schema_for(req, original) == projected
    assert original == before
    qualitative = qualitative_cmo_schema(original)
    assert qualitative_cmo_schema(qualitative) == qualitative
    assert original == before


@pytest.mark.parametrize("corruption", ["text_bound", "existing_pattern", "quote_bound", "numeric_ref",
                                         "scope", "external_ref", "support_ref_bounds"])
def test_unknown_contract_shape_refuses_before_model(corruption):
    from app.module_execution.executors.provider_schema import SchemaProjectionError
    req, original, _, _ = capture()
    if corruption == "text_bound":
        original["$defs"]["OtherStrategyStatement"]["properties"]["text"]["maxLength"] = 12
    elif corruption == "existing_pattern":
        original["$defs"]["OtherStrategyStatement"]["properties"]["text"]["pattern"] = "private"
    elif corruption == "quote_bound":
        original["$defs"]["NumericContext"]["properties"]["quote"]["maxLength"] = 12
    elif corruption == "numeric_ref":
        original["$defs"]["OtherStrategyStatement"]["properties"]["numeric_context"]["items"]["$ref"] = "#/$defs/OtherStrategyStatement"
    elif corruption == "scope":
        original["$id"] = "https://scope.invalid/"
    elif corruption == "external_ref":
        original["$defs"]["NumericContext"]["properties"]["quote"] = {"$ref":"https://external.invalid/"}
    else:
        original["$defs"]["AllowedEvidenceId"]["maxLength"] = 129
    saved = deepcopy(original)
    with pytest.raises(SchemaProjectionError):
        VirtualCMOExecutor(model_call=None).provider_schema_for(req, original)
    assert original == saved


@pytest.mark.parametrize("limit", ["entries", "bytes", "unknown_identity"])
def test_catalog_caps_and_scope_are_refused_safely(limit):
    from app.module_execution.executors.cmo_provider_contract import cmo_provider_schema
    from app.module_execution.executors.provider_schema import SchemaProjectionError
    _, original, _, ids = capture()
    if limit == "entries":
        rows = [{"support_id":ids["product_truth"], "exact_quote":f"Price {i} dollars"} for i in range(65)]
    elif limit == "bytes":
        rows = [{"support_id":ids["product_truth"], "exact_quote":"x" * 990 + str(i)} for i in range(20)]
    else:
        rows = [{"support_id":"evd_unknown", "exact_quote":PRICE}]
    with pytest.raises(SchemaProjectionError) as caught:
        cmo_provider_schema(original, rows)
    assert str(caught.value) == "cmo_provider_contract_unproved"


def test_complete_provider_schema_budget_is_checked_after_pair_expansion():
    from app.module_execution.executors.cmo_provider_contract import cmo_provider_schema
    from app.module_execution.executors.provider_schema import SchemaProjectionError
    _, original, _, ids = capture()
    original["properties"]["budget_literal"] = {"type":"string", "enum":[str(i) for i in range(940)]}
    original["required"].append("budget_literal")
    from app.module_execution.executors.support_schema import check_schema_bounds
    check_schema_bounds(original)
    rows = [{"support_id":ids["product_truth"], "exact_quote":f"Price {i} dollars"} for i in range(30)]
    with pytest.raises(SchemaProjectionError):
        cmo_provider_schema(original, rows)


def test_catalog_caps_are_an_intentional_subset_of_locally_valid_pairs():
    from dataclasses import replace
    req = invocation()
    extra = tuple(fact(f"numeric_{i}", f"Supplied value {i} units.") for i in range(70))
    req = replace(req, context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, *extra)))
    req, original, projected, ids = capture(req)
    from app.module_execution.executors.numeric_grounding import numeric_quote_catalog
    evidence = first_party_evidence(req, scoped_facts(req))
    rows = numeric_quote_catalog({e.record.evidence_id:e for e in evidence}, parent_claims(req))
    assert len(rows) == 64
    selected = {row["support_id"] for row in rows}
    omitted = next(e for e in evidence if e.input_key.startswith("numeric_") and e.record.evidence_id not in selected)
    value = output(ids, numeric_context=[{"support_id":omitted.record.evidence_id, "quote":omitted.value}])
    assert Draft202012Validator(original).is_valid(value)
    assert not Draft202012Validator(projected).is_valid(value)


@pytest.mark.parametrize("parents_present", [False, True])
def test_existing_local_and_parent_support_floors_are_retained(parents_present):
    from app.module_execution.executors.cmo_provider_contract import cmo_provider_schema
    from app.module_execution.executors.support_schema import SupportRequirement
    original = support_response_schema(StrategyOutput, ["evd_a"], ["clm_a"] if parents_present else [],
        requirement=SupportRequirement.PARENT_REQUIRED if parents_present else SupportRequirement.ANY)
    projected = cmo_provider_schema(original, [])
    ids = {"product_truth":"evd_a"}
    for evidence, parents in [([], []), (["evd_a"], []), ([], ["clm_a"]), (["evd_a"], ["clm_a"])]:
        value = output(ids, evidence_ids=evidence, parent_claim_ids=parents)
        assert Draft202012Validator(projected).is_valid(value) == Draft202012Validator(original).is_valid(value)


@pytest.mark.parametrize("projection_catalog", [False, True])
def test_complete_valid_pair_passes_executor_and_original_gates(projection_catalog):
    import asyncio
    import json
    from app.module_execution.acceptance import fully_accepted
    from app.orchestration_runtime.service import evaluate_result
    from tests.test_strategy_intelligence import IntelligenceModel
    req = invocation()
    calls = []
    async def model(**kwargs):
        calls.append(deepcopy(kwargs))
        result = json.loads(await IntelligenceModel()(**kwargs))
        data = json.loads(kwargs["text"])
        identity = next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == "product_truth")
        result["outputs"][0]["numeric_context"] = [{"support_id":identity, "quote":PRICE}]
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(result)
        return json.dumps(result)
    executor = VirtualCMOExecutor(model_call=model, numeric_quote_catalog_enabled=projection_catalog)
    result = asyncio.run(executor.execute(req))
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    assert len(calls) == 1 and result.schema_version == "virtual_cmo.payload.v1"
    assert ("numeric_quote_catalog" in json.loads(calls[0]["text"])) is projection_catalog
    assert result.payload["outputs"][0]["numeric_context"][0]["quote"] == PRICE


def test_catalog_advice_and_binding_are_not_enabled_by_projection():
    import asyncio
    from unittest.mock import patch
    from tests.test_strategy_intelligence import IntelligenceModel
    import json
    req = invocation()
    calls = []
    async def model(**kwargs):
        calls.append(kwargs)
        result = json.loads(await IntelligenceModel()(**kwargs))
        data = json.loads(kwargs["text"])
        identity = next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == "duration")
        result["outputs"][0]["evidence_ids"] = [next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == "product")]
        result["outputs"][0]["numeric_context"] = [{"support_id":identity, "quote":DURATION}]
        return json.dumps(result)
    from app.module_execution.executors.common import StatementSemanticsError, NumericContextFailureReason
    with patch("app.module_execution.executors.virtual_cmo.bind_numeric_context_citations") as binder:
        with pytest.raises(StatementSemanticsError) as caught:
            asyncio.run(VirtualCMOExecutor(model_call=model).execute(req))
    assert caught.value.numeric_context_reason is NumericContextFailureReason.SUPPORT_NOT_CITED
    binder.assert_not_called()
    assert len(calls) == 1 and "numeric_quote_catalog" not in json.loads(calls[0]["text"])


@pytest.mark.parametrize("field", ["text", "items"])
def test_unicode_decimal_digits_still_fail_original_server_guard(field):
    import asyncio
    import json
    from tests.test_strategy_intelligence import IntelligenceModel
    from app.module_execution.executors.common import ExecutorOutputError
    req = invocation()
    async def model(**kwargs):
        result = json.loads(await IntelligenceModel()(**kwargs))
        result["outputs"][0][field] = "Compare \u0662 options" if field == "text" else ["Compare \u0662 options"]
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(result)
        return json.dumps(result)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model).execute(req))
    from app.module_execution.executors.common import OutputFailureStage
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_multiple_complete_quotes_from_one_source_share_one_closed_pair_branch():
    from dataclasses import replace
    req = invocation()
    facts = tuple(replace(item, value={"pricing":PRICE, "duration":DURATION})
        if item.label == "product_truth" else item for item in req.context_packet.known_facts)
    req = replace(req, context_packet=replace(req.context_packet, known_facts=facts))
    _, _, projected, ids = capture(req)
    branch = next(branch for branch in projected["$defs"]["NumericContext"]["anyOf"]
        if branch["properties"]["support_id"]["enum"] == [ids["product_truth"]])
    assert set(branch["properties"]["quote"]["enum"]) == {PRICE, DURATION}
    assert branch["additionalProperties"] is False
    assert set(branch["required"]) == {"support_id", "quote"}
    for quote in (PRICE, DURATION):
        assert Draft202012Validator(projected).is_valid(output(ids,
            numeric_context=[{"support_id":ids["product_truth"], "quote":quote}]))


def test_original_field_and_array_bounds_are_preserved():
    _, original, projected, ids = capture()
    for name in ("MainGrowthConstraintStatement", "OtherStrategyStatement"):
        before = original["$defs"][name]["properties"]
        after = projected["$defs"][name]["properties"]
        for field in ("evidence_ids", "parent_claim_ids", "numeric_context"):
            assert before[field] == after[field]
        assert before["text"]["maxLength"] == after["text"]["maxLength"] == 4000
        assert before["items"]["minItems"] == after["items"]["minItems"] == 1
        assert before["items"]["maxItems"] == after["items"]["maxItems"]
        assert before["items"]["items"]["maxLength"] == after["items"]["items"]["maxLength"] == 300
    for changes in ({"text":"x" * 4001}, {"items":["x" * 301]}, {"items":["a", "b"]},
                    {"numeric_context":[{"support_id":ids["product_truth"], "quote":PRICE}] * 4},
                    {"evidence_ids":[ids["product_truth"]] * 33}):
        assert not Draft202012Validator(projected).is_valid(output(ids, **changes))
