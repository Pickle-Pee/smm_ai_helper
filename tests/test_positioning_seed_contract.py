"""Request-scoped Positioning generation, parsing and safe semantic diagnostics."""
from dataclasses import replace
import json
import traceback
from unittest.mock import Mock

import pytest

from app.module_execution.executors import ExecutorOutputError, PositioningExecutor
from app.module_execution.executors.common import (
    OutputFailureStage, SemanticRule, StatementSemanticsError,
)
from app.module_execution.executors.schemas import OutputStatement, PositioningOutput
from app.module_registry import ModuleId
from tests.positioning_provider import allowed_kinds
from tests.test_module_executors import FakeModel, dispatch, fact, request


JOB_OUTPUTS = ("JTBD_frame", "demand_context")
ALTERNATIVE_OUTPUTS = ("category", "frame_of_reference", "points_of_parity")
GUARDED_OUTPUTS = (*JOB_OUTPUTS, *ALTERNATIVE_OUTPUTS)
DIFFERENTIATION_OUTPUTS = ("differentiation", "points_of_difference", "USP_directions")
KINDS = {"OBSERVATION", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"}
STATES = ((True, True), (False, True), (True, False), (False, False))


def seed_request(job, alternative, **kwargs):
    facts = [fact(key) for key in ("product", "target_or_target_hypothesis", "product_truth")]
    if job:
        facts.append(fact("customer_job_or_need"))
    if alternative:
        facts.append(fact("relevant_alternative"))
    return request(ModuleId.POSITIONING, facts=tuple(facts), **kwargs)


@pytest.mark.parametrize("job,alternative", STATES)
def test_provider_schema_four_seed_states_and_payload_compatibility(job, alternative):
    model = FakeModel()
    result = dispatch(seed_request(job, alternative), model)
    schema = model.calls[0]["response_schema"]
    for names, supplied in ((JOB_OUTPUTS, job), (ALTERNATIVE_OUTPUTS, alternative)):
        for name in names:
            assert allowed_kinds(schema, name) == (KINDS if supplied else {"HYPOTHESIS"})
    for name in DIFFERENTIATION_OUTPUTS:
        assert allowed_kinds(schema, name) == {"HYPOTHESIS"}
    assert result.schema_version == "positioning.payload.v1"
    assert set(result.payload) == {"outputs", "assumptions", "limitations"}
    assert len(model.calls) == 1
    notices = " ".join(result.payload["limitations"])
    assert ("customer_job_or_need was not supplied" in notices) is (not job)
    assert ("relevant_alternative was not supplied" in notices) is (not alternative)


@pytest.mark.parametrize("job,alternative,name", [
    (False, True, name) for name in JOB_OUTPUTS
] + [
    (True, False, name) for name in ALTERNATIVE_OUTPUTS
] + [
    (False, False, name) for name in GUARDED_OUTPUTS
])
@pytest.mark.parametrize("kind", sorted(KINDS - {"HYPOTHESIS"}))
def test_nonhypothesis_missing_seed_is_rejected_by_selected_parser(job, alternative, name, kind):
    model = FakeModel(lambda payload, _: payload["outputs"][0].update(kind=kind))
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(seed_request(job, alternative, outputs=(name,)), model)
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID
    assert allowed_kinds(model.calls[0]["response_schema"], name) == {"HYPOTHESIS"}
    assert len(model.calls) == 1


@pytest.mark.parametrize("name", GUARDED_OUTPUTS)
@pytest.mark.parametrize("kind", sorted(KINDS))
def test_supplied_seed_permits_ordinary_statement_kinds(name, kind):
    model = FakeModel(lambda payload, _: payload["outputs"][0].update(kind=kind))
    result = dispatch(seed_request(True, True, outputs=(name,)), model)
    assert result.payload["outputs"][0]["kind"] == kind


def test_authorized_seed_identity_in_scoped_project_context_is_supplied():
    invocation = seed_request(True, True)
    facts = invocation.context_packet.known_facts
    invocation = replace(invocation, context_packet=replace(invocation.context_packet,
        known_facts=facts[:3], relevant_project_context=facts[3:]))
    model = FakeModel()
    dispatch(invocation, model)
    schema = model.calls[0]["response_schema"]
    assert all(allowed_kinds(schema, name) == KINDS for name in GUARDED_OUTPUTS)


@pytest.mark.parametrize("job,alternative", STATES)
@pytest.mark.parametrize("name", DIFFERENTIATION_OUTPUTS)
@pytest.mark.parametrize("kind", sorted(KINDS - {"HYPOTHESIS"}))
def test_static_differentiation_contract_composes_with_every_seed_state(job, alternative, name, kind):
    model = FakeModel(lambda payload, _: payload["outputs"][0].update(kind=kind))
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(seed_request(job, alternative, outputs=(name,)), model)
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


@pytest.mark.parametrize("seed,names", [
    ("customer_job_or_need", JOB_OUTPUTS), ("relevant_alternative", ALTERNATIVE_OUTPUTS),
])
@pytest.mark.parametrize("invalid", ["unauthorized", "empty", "whitespace", "nested-empty", "prose"])
def test_seed_presence_requires_authorized_nonempty_input_identity(seed, names, invalid):
    invocation = seed_request(False, False)
    seed_fact = fact(seed)
    if invalid == "unauthorized":
        seed_fact = replace(seed_fact, authorized=False)
    elif invalid == "empty":
        seed_fact = replace(seed_fact, value=())
    elif invalid == "whitespace":
        seed_fact = replace(seed_fact, value="   ")
    elif invalid == "nested-empty":
        seed_fact = replace(seed_fact, value={"empty": []})
    else:
        seed_fact = fact("business_goal", f"The prose mentions {seed} and a plausible seed value")
    packet = replace(invocation.context_packet,
        known_facts=(*invocation.context_packet.known_facts, seed_fact),
        assumptions=(f"{seed} supplied in assumption prose",),
        evidence=(f"{seed} supplied in unscoped evidence prose",))
    invocation = replace(invocation, objective=f"{seed} supplied in objective prose", context_packet=packet)
    model = FakeModel()
    dispatch(invocation, model)
    schema = model.calls[0]["response_schema"]
    assert all(allowed_kinds(schema, name) == {"HYPOTHESIS"} for name in names)
    local = json.loads(model.calls[0]["text"])["local_evidence"]
    assert seed not in {item["input_key"] for item in local}


@pytest.mark.parametrize("name,rule", [
    *((name, SemanticRule.MISSING_SEED_REQUIRES_HYPOTHESIS) for name in GUARDED_OUTPUTS),
    *((name, SemanticRule.DIFFERENTIATION_REQUIRES_HYPOTHESIS) for name in DIFFERENTIATION_OUTPUTS),
    *((name, SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH)
      for name in ("RTB", "value_proposition", "positioning_statement", "offer")),
])
def test_semantics_remain_defense_in_depth_when_wire_validation_is_bypassed(name, rule):
    statement = OutputStatement(output_name=name, text="PRIVATE_MODEL_TEXT", kind="INFERENCE",
        confidence="MEDIUM", evidence_ids=[], parent_claim_ids=[])
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement, {}, {})
    assert caught.value.rule is rule
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    assert "PRIVATE_MODEL_TEXT" not in str(caught.value)


@pytest.fixture
def warning(monkeypatch):
    from app.module_execution.executors.common import log
    warning = Mock()
    monkeypatch.setattr(log, "warning", warning)
    return warning


@pytest.mark.parametrize("name", ["RTB", "value_proposition", "positioning_statement", "offer"])
def test_product_support_fails_closed_with_safe_server_rule(name, warning):
    invocation = seed_request(False, False, outputs=(name,))
    facts = tuple(replace(item, value="PRIVATE_EVIDENCE_VALUE") for item in invocation.context_packet.known_facts)
    invocation = replace(invocation, objective="PRIVATE_BUSINESS_TEXT",
        context_packet=replace(invocation.context_packet, known_facts=facts))

    def unsupported(payload, data):
        payload["outputs"][0].update(text="PRIVATE_MODEL_TEXT", evidence_ids=[
            next(item["evidence_id"] for item in data["local_evidence"] if item["input_key"] == "product")])

    model = FakeModel(unsupported)
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(invocation, model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    warning.assert_called_once_with("Module output rejected module=%s stage=%s rule=%s",
        "POSITIONING", "statement_semantics_invalid", "product_claim_requires_truth")
    diagnostics = str(warning.call_args) + "".join(traceback.format_exception(caught.value))
    for private in ("PRIVATE_MODEL_TEXT", "PRIVATE_EVIDENCE_VALUE", "PRIVATE_BUSINESS_TEXT"):
        assert private not in diagnostics
    assert not hasattr(caught.value, "rule")
    assert len(model.calls) == 1


def test_missing_seed_semantic_rule_is_logged_when_parser_is_bypassed(monkeypatch, warning):
    monkeypatch.setattr(PositioningExecutor, "output_type_for", lambda *_: PositioningOutput)
    model = FakeModel(lambda payload, _: payload["outputs"][0].update(kind="OBSERVATION"))
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(seed_request(False, False, outputs=("JTBD_frame",)), model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    warning.assert_called_once_with("Module output rejected module=%s stage=%s rule=%s",
        "POSITIONING", "statement_semantics_invalid", "missing_seed_requires_hypothesis")


def test_arbitrary_semantic_exception_message_is_never_logged(monkeypatch, warning):
    def reject(*_):
        raise ValueError("PRIVATE_RAW_EXCEPTION https://private.example/model")
    monkeypatch.setattr(PositioningExecutor, "validate_statement", reject)
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(seed_request(False, False))
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    warning.assert_called_once_with("Module output rejected module=%s stage=%s",
        "POSITIONING", "statement_semantics_invalid")
    diagnostics = str(warning.call_args) + "".join(traceback.format_exception(caught.value))
    assert "PRIVATE_RAW_EXCEPTION" not in diagnostics
    assert "https://private.example" not in diagnostics


def test_semantic_rule_codes_are_bounded_server_constants():
    assert {rule.value for rule in SemanticRule} == {
        "missing_seed_requires_hypothesis", "differentiation_requires_hypothesis",
        "product_claim_requires_truth",
    }
    with pytest.raises(TypeError):
        StatementSemanticsError("PRIVATE_ARBITRARY_RULE")
