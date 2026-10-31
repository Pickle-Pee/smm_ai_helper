"""Qualitative observations require actual cited factual assertion support."""
from types import SimpleNamespace
from copy import deepcopy
import asyncio
import json

from jsonschema import Draft202012Validator

import pytest

from app.marketing_orchestrator.quality_gates.contracts import ClaimType
from app.module_execution.executors import PositioningExecutor
from app.module_execution.executors.common import (
    StatementSemanticsError, SemanticRule, first_party_evidence, scoped_facts, plain, OutputFailureStage,
)
from app.module_execution.executors import ExecutorOutputError
from app.module_execution.executors.positioning_observation_schema import positioning_observation_schema
from app.module_execution.executors.provider_schema import SchemaProjectionError, nodes
from app.module_execution.executors.support_schema import support_response_schema
from app.module_registry import ModuleId
from tests.test_module_executors import FakeModel, dispatch, request
from tests.test_positioning_seed_contract import seed_request
from tests.positioning_provider import PositioningProvider
from tests.test_graph_model_adapter import install_transport
from app.orchestration_runtime.model_adapter import production_model_call
from app.module_execution.executors.schemas import OutputStatement


def statement(text, *, output="category", kind="OBSERVATION", evidence=("evd_seed",), parents=()):
    return OutputStatement(output_name=output, text=text, kind=kind, confidence="MEDIUM",
        evidence_ids=list(evidence), parent_claim_ids=list(parents))


def sources(text="An offline workshop for beginners."):
    return {"evd_seed": SimpleNamespace(input_key="relevant_alternative", value=text)}


@pytest.mark.parametrize("output,text", [
    ("category", "An offline workshop competing with hobby clubs."),
    ("points_of_parity", "Like other introductory workshops, we meet expected standards."),
])
def test_unsupplied_qualitative_observation_is_rejected(output, text):
    # Public synthetic reproduction of the observed failure class, not business data.
    with pytest.raises(StatementSemanticsError):
        PositioningExecutor(model_call=None).validate_statement(statement(text, output=output), sources(), {})


@pytest.mark.parametrize("kind", ["INFERENCE", "HYPOTHESIS", "RECOMMENDATION"])
def test_qualitative_reasoning_retains_existing_kinds(kind):
    PositioningExecutor(model_call=None).validate_statement(
        statement("A possible competitive frame to validate.", kind=kind), sources(), {})


def test_local_observation_is_a_literal_quote_from_its_own_cited_source():
    local = sources("Owner context. An offline workshop for beginners. More context.")
    executor = PositioningExecutor(model_call=None)
    executor.validate_statement(statement("An offline workshop for beginners."), local, {})
    local["evd_uncited"] = SimpleNamespace(input_key="product", value="A hobby club.")
    for text in ("A hobby club.", "A beginners workshop offline.", "An offline workshop. More context."):
        with pytest.raises(StatementSemanticsError) as caught:
            executor.validate_statement(statement(text), local, {})
        assert caught.value.rule is SemanticRule.OBSERVATION_SUPPORT_REQUIRED


@pytest.mark.parametrize("kind", list(ClaimType))
def test_only_actually_cited_factual_parent_can_authorize_observation(kind):
    parents = {"clm_selected": SimpleNamespace(value="An offline workshop for beginners.", claim_type=kind),
               "clm_uncited": SimpleNamespace(value="A hobby club.", claim_type=ClaimType.FACT)}
    observed = statement("An offline workshop for beginners.", output="target", evidence=(), parents=("clm_selected",))
    executor = PositioningExecutor(model_call=None)
    if kind in (ClaimType.FACT, ClaimType.OBSERVATION):
        executor.validate_statement(observed, {}, parents)
    else:
        with pytest.raises(StatementSemanticsError) as caught:
            executor.validate_statement(observed, {}, parents)
        assert caught.value.rule is SemanticRule.OBSERVATION_SUPPORT_REQUIRED
    with pytest.raises(StatementSemanticsError):
        executor.validate_statement(observed.model_copy(update={"text": "A hobby club."}), {}, parents)


@pytest.mark.parametrize("text", ["Contact 10 customers.", "Contact ٥ customers."])
def test_numeric_rule_precedes_observation_rule(text):
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement(text), sources(), {})
    assert caught.value.rule is SemanticRule.NUMERICAL_SUPPORT_REQUIRED


def test_strategy_context_quote_and_serialized_metadata_are_not_factual_assertions():
    value = json.dumps({"summary": "An offline workshop.", "items": ["Try a pilot."],
        "numeric_context": [{"support_id": "evd_quote", "quote": "Contact 10 customers."}]})
    parents = {"clm_selected": SimpleNamespace(value=value, claim_type=ClaimType.OBSERVATION)}
    executor = PositioningExecutor(model_call=None)
    for text in ("Contact 10 customers.", "evd_quote", "numeric_context"):
        with pytest.raises(StatementSemanticsError):
            executor.validate_statement(statement(text, output="target", evidence=(), parents=("clm_selected",)), {}, parents)
    executor.validate_statement(statement("An offline workshop.", output="target", evidence=(), parents=("clm_selected",)), {}, parents)


@pytest.mark.parametrize("job,alternative", [(True, True), (False, True), (True, False), (False, False)])
@pytest.mark.parametrize("mode", ["default", "projection", "product_wire", "product_projection", "minimal"])
@pytest.mark.parametrize("partial", [False, True])
def test_provider_subset_all_modes_preserves_original_schema_and_source_contract(job, alternative, mode, partial):
    invocation = seed_request(job, alternative, **({"outputs": ("target",)} if partial else {}))
    executor = PositioningExecutor(model_call=None, provider_schema_projection="projection" in mode,
        product_support_wire="product" in mode, minimal_provider_schema=mode == "minimal")
    evidence = first_party_evidence(invocation, scoped_facts(invocation))
    canonical = support_response_schema(executor.output_type_for(invocation, evidence),
        [e.record.evidence_id for e in evidence], [])
    original = deepcopy(canonical)
    wire = executor.wire_schema_for(invocation, canonical, evidence)
    wire_before = deepcopy(wire)
    provider = executor.provider_schema_for(invocation, wire)
    assert canonical == original and wire == wire_before
    assert positioning_observation_schema(provider, minimal=mode == "minimal") == provider
    assert "OBSERVATION" in json.dumps(canonical)
    for node in nodes(provider):
        kind = node.get("properties", {}).get("kind")
        if kind is not None:
            values = kind.get("enum", [kind.get("const")])
            assert "OBSERVATION" not in values and set(values) <= {"INFERENCE", "HYPOTHESIS", "RECOMMENDATION"}
            if "enum" in kind:
                assert "INFERENCE" in values
    if mode != "minimal":
        # The only kind differences are the explicit removal of OBSERVATION.
        restored = deepcopy(provider)
        for node in nodes(restored):
            kind = node.get("properties", {}).get("kind")
            if kind is not None and "enum" in kind:
                kind["enum"].insert(0, "OBSERVATION")
        for node in nodes(wire):
            kind = node.get("properties", {}).get("kind")
            if kind is not None and "enum" in kind:
                assert kind["enum"] == ["OBSERVATION", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"]
        # Projection has its own independent equivalence tests; compare kind sets.
        assert {tuple(n["properties"]["kind"].get("enum", [])) for n in nodes(restored)
                if "kind" in n.get("properties", {})} == {
                tuple(n["properties"]["kind"].get("enum", [])) for n in nodes(wire)
                if "kind" in n.get("properties", {})}


@pytest.mark.parametrize("kind_schema", [{"type": "string"}, {"$ref": "#/$defs/Unknown"},
    {"type": "string", "enum": ["OBSERVATION"]}, {"type": "string", "enum": ["UNKNOWN"]}])
def test_unknown_provider_kind_shape_fails_closed(kind_schema):
    with pytest.raises(SchemaProjectionError):
        positioning_observation_schema({"properties": {"kind": kind_schema}})


def test_exact_local_observation_remains_valid_on_canonical_server_path():
    def exact(payload, data):
        source = next(e for e in data["local_evidence"] if e["input_key"] == "product_truth")
        payload["outputs"][0].update(kind="OBSERVATION", text=source["value"], evidence_ids=[source["evidence_id"]])
    model = FakeModel(exact)
    result = dispatch(request(ModuleId.POSITIONING, outputs=("RTB",)), model)
    # Deliberately bypass the provider restriction with the test double: the
    # original canonical validator must retain supported historical OBS shape.
    assert result.payload["outputs"][0]["kind"] == "OBSERVATION"
    assert not Draft202012Validator(model.calls[0]["response_schema"]).is_valid(plain(result.payload))


def test_no_support_floor_and_duplicate_references_still_fail_before_observation():
    for change, stage in (({"evidence_ids": [], "parent_claim_ids": []}, OutputFailureStage.SCHEMA_INVALID),
                          (None, OutputFailureStage.SUPPORT_IDENTITY_INVALID)):
        def mutate(payload, data):
            output = payload["outputs"][0]
            output.update(kind="OBSERVATION", text="An unsupported assertion.")
            if change is not None:
                output.update(change)
            else:
                output["evidence_ids"].append(output["evidence_ids"][0])
        with pytest.raises(ExecutorOutputError) as caught:
            dispatch(request(ModuleId.POSITIONING, outputs=("target",)), FakeModel(mutate))
        assert caught.value.stage is stage


def test_actual_http_adapter_enforces_narrowed_generation_and_keeps_all_outputs(monkeypatch):
    provider = PositioningProvider()
    install_transport(monkeypatch, provider)
    invocation = request(ModuleId.POSITIONING)
    result = asyncio.run(PositioningExecutor(model_call=production_model_call).execute(invocation))
    assert len(provider.calls) == 1 and len(result.normalized_result.claims) == 16
    assert {s["output_name"] for s in result.payload["outputs"]} == set(invocation.expected_outputs)
    assert all(s["kind"] != "OBSERVATION" for s in result.payload["outputs"])
    body = provider.calls[0]
    assert body["text"]["format"]["strict"] is True
    assert all("OBSERVATION" not in node.get("properties", {}).get("kind", {}).get("enum", [])
               for node in nodes(body["text"]["format"]["schema"]))


@pytest.mark.parametrize("extra", [{"$ref": "#/$defs/Unknown"}, {"anyOf": [{"const": "OBSERVATION"}]},
    {"not": {"const": "HYPOTHESIS"}}, {"pattern": "OBSERVATION"}, {"description": "Unreviewed annotation"},
    {"title": ["Unknown annotation shape"]}])
def test_unexpected_kind_siblings_fail_closed_without_mutating_caller(extra):
    schema = {"properties": {"kind": {"type": "string", "enum": ["OBSERVATION", "HYPOTHESIS"], **extra}}}
    before = deepcopy(schema)
    with pytest.raises(SchemaProjectionError):
        positioning_observation_schema(schema)
    assert schema == before


@pytest.mark.parametrize("malformed", [None, [], "string"])
def test_malformed_kind_and_properties_raise_bounded_projection_error(malformed):
    for schema in ({"properties": malformed}, {"properties": {"kind": malformed}}):
        with pytest.raises(SchemaProjectionError):
            positioning_observation_schema(schema)


def test_unknown_kind_shape_prevents_model_dispatch(monkeypatch):
    from app.module_execution.executors import common
    original = common.support_response_schema
    def unexpected(*args, **kwargs):
        schema = original(*args, **kwargs)
        for node in nodes(schema):
            if "kind" in node.get("properties", {}):
                node["properties"]["kind"]["not"] = {"const": "HYPOTHESIS"}
        return schema
    monkeypatch.setattr(common, "support_response_schema", unexpected)
    model = FakeModel()
    with pytest.raises(SchemaProjectionError):
        dispatch(request(ModuleId.POSITIONING), model)
    assert model.calls == []


def test_observation_failure_diagnostic_is_closed_and_contains_no_prose(monkeypatch):
    from unittest.mock import Mock
    from app.module_execution.executors import common
    warning = Mock()
    monkeypatch.setattr(common.log, "warning", warning)
    private = "PRIVATE_UNSUPPORTED_QUALITATIVE_PROSE"
    model = FakeModel(lambda p,d: p["outputs"][0].update(kind="OBSERVATION", text=private))
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(request(ModuleId.POSITIONING, outputs=("target",)), model)
    warning.assert_called_once_with("Module output rejected module=%s stage=%s rule=%s",
        "POSITIONING", "statement_semantics_invalid", "observation_support_required")
    assert private not in str(warning.call_args) + str(caught.value)
    assert len(model.calls) == 1



def test_diagnostic_control_retains_full_canonical_enum_while_production_is_narrowed():
    from tools.positioning_diagnostics import capture_request
    invocation = request(ModuleId.POSITIONING)
    baseline = asyncio.run(capture_request(invocation, model="gpt-5-mini"))
    model = FakeModel()
    dispatch(invocation, model)
    canonical = baseline.arguments["response_schema"]
    actual = model.calls[0]["response_schema"]
    assert actual == positioning_observation_schema(canonical)
    assert any("OBSERVATION" in n.get("properties", {}).get("kind", {}).get("enum", []) for n in nodes(canonical))
    assert baseline.arguments["instruction"] == model.calls[0]["instruction"]
    assert baseline.payload["text"]["format"]["schema"] == canonical



@pytest.mark.parametrize("output,rule", [("JTBD_frame", SemanticRule.MISSING_SEED_REQUIRES_HYPOTHESIS),
    ("offer", SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH)])
def test_existing_seed_and_product_guard_precede_observation_and_numeric(output, rule):
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(
            OutputStatement.model_construct(output_name=output, text="Invented 10 customers.",
                kind="OBSERVATION", confidence="MEDIUM", evidence_ids=[], parent_claim_ids=[]), {}, {})
    assert caught.value.rule is rule


def test_numeric_local_observation_remains_allowed_verbatim():
    PositioningExecutor(model_call=None).validate_statement(
        statement("A workshop lasting 6 weeks."), sources("A workshop lasting 6 weeks."), {})


def test_actual_accepted_observation_parent_is_valid_on_canonical_server_path():
    from app.module_execution import UpstreamExecutionResult
    def parent_observation(payload, data):
        source = next(e for e in data["local_evidence"] if e["input_key"] == "product_truth")
        payload["outputs"][0].update(kind="OBSERVATION", text=source["value"], evidence_ids=[source["evidence_id"]])
    parent = dispatch(request(ModuleId.POSITIONING, outputs=("target",), identity="observation-parent"), FakeModel(parent_observation))
    def child_observation(payload, data):
        payload["outputs"][0].update(kind="OBSERVATION", text=parent.normalized_result.claims[0].value,
            evidence_ids=[], parent_claim_ids=data["allowed_parent_claim_ids"])
    invocation = request(ModuleId.POSITIONING, outputs=("target",), identity="observation-child",
        upstream=(UpstreamExecutionResult(producer_node_id="accepted_positioning", result=parent),))
    child = dispatch(invocation, FakeModel(child_observation))
    assert child.normalized_result.claims[0].claim_type is ClaimType.OBSERVATION
    assert child.normalized_result.claims[0].parent_claim_ids == (parent.normalized_result.claims[0].claim_id,)
    assert not child.normalized_result.claims[0].evidence_ids
