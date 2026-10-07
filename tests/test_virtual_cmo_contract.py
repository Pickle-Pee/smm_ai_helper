"""Structural strategy constraints and independent runtime defenses."""
import json
import traceback
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

from app.module_execution.executors.common import (
    BaseExecutor, ExecutorOutputError, OutputFailureStage, first_party_evidence,
    parent_claims, scoped_facts, SemanticRule, StatementSemanticsError,
)
from app.module_execution.executors.intelligence_schemas import (
    StrategyOutput, MainGrowthConstraintStatement, OtherStrategyStatement,
)
from app.module_execution.executors.schemas import OutputBase, OutputStatement
from app.module_execution.executors.support_schema import SupportRequirement, support_response_schema
from pydantic import Field
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.module_registry import ModuleId
from tests.test_module_executors import request
from tests.test_strategy_intelligence import IntelligenceModel, run, valid_request


GAPS = [
    ("strategic_diagnosis", {"kind": "OBSERVATION"}),
    ("strategic_diagnosis", {"kind": "INFERENCE"}),
    ("main_growth_constraint", {"kind": "RECOMMENDATION"}),
    ("main_growth_constraint", {"items": ["one", "two"]}),
    ("strategic_diagnosis", {"parent_claim_ids": []}),
]


@pytest.mark.parametrize("name,changes", GAPS)
def test_proven_gaps_now_rejected_by_exact_emitted_schema(name, changes):
    req = valid_request(ModuleId.VIRTUAL_CMO)
    req = request(req.module_id, facts=req.context_packet.known_facts,
                  upstream=req.upstream_results, outputs=(name,))
    model = IntelligenceModel(use_parents=True)
    run(req, model=model)
    data = json.loads(model.calls[0]["text"])
    # An OBSERVATION quotes cited local support, isolating the strategy kind rule.
    statement = dict(output_name=name, kind="HYPOTHESIS", confidence="MEDIUM",
                     text=data["local_evidence"][0]["value"], items=["one"],
                     evidence_ids=[data["local_evidence"][0]["evidence_id"]],
                     parent_claim_ids=data["allowed_parent_claim_ids"])
    statement.update(changes)
    payload = dict(outputs=[statement], assumptions=[], limitations=[])
    assert not Draft202012Validator(model.calls[0]["response_schema"]).is_valid(payload)
    ignoring_provider = IntelligenceModel(use_parents=True)
    with pytest.raises(ExecutorOutputError) as caught:
        run(req, lambda raw, _: raw["outputs"][0].update(statement), model=ignoring_provider)
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID
    assert len(ignoring_provider.calls) == 1


@pytest.mark.parametrize("name,changes", GAPS)
def test_runtime_defenses_bypass_schema_and_parser(name, changes):
    req = valid_request(ModuleId.VIRTUAL_CMO)
    evidence = first_party_evidence(req, scoped_facts(req))
    parents = parent_claims(req)
    statement = OtherStrategyStatement.model_construct(output_name=name,
        text=evidence[0].value, kind="HYPOTHESIS", confidence="MEDIUM",
        items=["one"], evidence_ids=[evidence[0].record.evidence_id],
        parent_claim_ids=list(parents))
    for field, value in changes.items():
        setattr(statement, field, value)
    req = request(req.module_id, facts=req.context_packet.known_facts,
                  upstream=req.upstream_results, outputs=(name,))
    with pytest.raises(ExecutorOutputError) as caught:
        BaseExecutor.build_result(VirtualCMOExecutor(model_call=None), req,
            StrategyOutput.model_construct(outputs=[statement], assumptions=[], limitations=[]),
            evidence, parents)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    expected = (SemanticRule.STRATEGY_KIND_INVALID if changes.get("kind") in ("OBSERVATION", "INFERENCE")
                else SemanticRule.STRATEGY_PARENT_REQUIRED if "parent_claim_ids" in changes
                else SemanticRule.MAIN_GROWTH_CONSTRAINT_INVALID)
    assert caught.value.rule is expected


@pytest.mark.parametrize("model,name", [
    (MainGrowthConstraintStatement, "main_growth_constraint"),
    (OtherStrategyStatement, "strategic_priorities"),
])
def test_static_strategy_contract(model, name):
    schema = StrategyOutput.model_json_schema()
    props = schema["$defs"][model.__name__]["properties"]
    assert props["items"]["minItems"] == 1
    assert props["items"]["maxItems"] == (1 if name == "main_growth_constraint" else 3)
    assert (props["kind"].get("enum") or [props["kind"]["const"]]) == (
        ["HYPOTHESIS"] if name == "main_growth_constraint" else ["HYPOTHESIS", "RECOMMENDATION"])
    validator = Draft202012Validator(schema)
    for kind in ("OBSERVATION", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"):
        for count in range(5):
            payload = dict(outputs=[dict(output_name=name, kind=kind, text="Synthetic",
                confidence="MEDIUM", evidence_ids=["evd_local"], parent_claim_ids=[],
                items=["one"] * count)], assumptions=[], limitations=[])
            assert validator.is_valid(payload) is (
                kind in (["HYPOTHESIS"] if name == "main_growth_constraint" else ["HYPOTHESIS", "RECOMMENDATION"])
                and 1 <= count <= (1 if name == "main_growth_constraint" else 3))


@pytest.mark.parametrize("parents", [False, True])
@pytest.mark.parametrize("evidence,refs", [([], []), (["evd_local"], []),
                                          ([], ["clm_parent"]), (["evd_local"], ["clm_parent"])])
def test_request_parent_policy_matrix(parents, evidence, refs):
    policy = SupportRequirement.PARENT_REQUIRED if parents else SupportRequirement.ANY
    schema = support_response_schema(StrategyOutput, ["evd_local"],
                                    ["clm_parent"] if parents else [], requirement=policy)
    for name in ("main_growth_constraint", "strategic_priorities"):
        payload = dict(outputs=[dict(output_name=name, text="Synthetic", kind="HYPOTHESIS",
            confidence="MEDIUM", evidence_ids=evidence, parent_claim_ids=refs, items=["one"])],
            assumptions=[], limitations=[])
        assert Draft202012Validator(schema).is_valid(payload) is (
            bool(refs) if parents else bool(evidence) and not refs)


class BypassStatement(OutputStatement):
    items: list[str] = Field(min_length=1, max_length=3)


class BypassOutput(OutputBase):
    outputs: list[BypassStatement]


@pytest.mark.parametrize("name,changes", GAPS)
def test_bounded_strategy_rule_logging_after_internal_schema_bypass(name, changes, monkeypatch):
    req = valid_request(ModuleId.VIRTUAL_CMO)
    req = request(req.module_id, facts=req.context_packet.known_facts,
                  upstream=req.upstream_results, outputs=(name,))
    # Explicitly emulate a legacy internal wire type and generic support policy.
    monkeypatch.setattr(VirtualCMOExecutor, "output_type", BypassOutput)
    monkeypatch.setattr(VirtualCMOExecutor, "support_requirement_for", lambda *_: SupportRequirement.ANY)
    warning = Mock()
    monkeypatch.setattr("app.module_execution.executors.common.log.warning", warning)
    def invalid(raw, data):
        raw["outputs"][0].update(items=["PRIVATE_ITEM"], text=data["local_evidence"][0]["value"])
        raw["outputs"][0].update(changes)
    with pytest.raises(ExecutorOutputError) as caught:
        run(req, invalid)
    rule = ("strategy_kind_invalid" if changes.get("kind") in ("OBSERVATION", "INFERENCE")
            else "strategy_parent_required" if "parent_claim_ids" in changes
            else "main_growth_constraint_invalid")
    warning.assert_called_once_with("Module output rejected module=%s stage=%s rule=%s",
                                    "VIRTUAL_CMO", "statement_semantics_invalid", rule)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    assert "PRIVATE_ITEM" not in str(warning.call_args) + "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("field", ["text", "items"])
def test_numerical_rule_logs_no_content(field, monkeypatch):
    warning = Mock()
    monkeypatch.setattr("app.module_execution.executors.common.log.warning", warning)
    secret = "PRIVATE_NUMBER conversion improves by 29%"
    def invalid(raw, data):
        raw["outputs"][0][field] = [secret] if field == "items" else secret
    model = IntelligenceModel(use_parents=True)
    with pytest.raises(ExecutorOutputError) as caught:
        run(valid_request(ModuleId.VIRTUAL_CMO), invalid, model=model)
    warning.assert_called_once_with("Module output rejected module=%s stage=%s rule=%s",
        "VIRTUAL_CMO", "statement_semantics_invalid", "numerical_support_required")
    assert secret not in str(warning.call_args) + "".join(traceback.format_exception(caught.value))
    assert len(model.calls) == 1


def test_numeric_support_verbatim_invariant():
    from app.module_execution.executors.intelligence_common import require_supported_numbers
    sentence = "Budget 500 dollars"
    require_supported_numbers(sentence, ["Supplied: " + sentence])
    require_supported_numbers("Qualitative priority", [])
    for unsupported in ("Budget 501 dollars", "Budget 1000 dollars", "500 dollars budget"):
        with pytest.raises(StatementSemanticsError) as caught:
            require_supported_numbers(unsupported, [sentence])
        assert caught.value.rule is SemanticRule.NUMERICAL_SUPPORT_REQUIRED


@pytest.mark.parametrize("field", ["text", "items"])
def test_numeric_runtime_defense_without_schema(field):
    req = valid_request(ModuleId.VIRTUAL_CMO)
    evidence = first_party_evidence(req, scoped_facts(req))
    parents = parent_claims(req)
    statement = OtherStrategyStatement.model_construct(output_name="strategic_diagnosis",
        text="Qualitative hypothesis", kind="HYPOTHESIS", confidence="MEDIUM", items=["One"],
        evidence_ids=[evidence[0].record.evidence_id], parent_claim_ids=list(parents))
    setattr(statement, field, ["Unsupported 29%"] if field == "items" else "Unsupported 29%")
    with pytest.raises(StatementSemanticsError) as caught:
        VirtualCMOExecutor(model_call=None).validate_statement(statement,
            {e.record.evidence_id: e for e in evidence}, parents)
    assert caught.value.rule is SemanticRule.NUMERICAL_SUPPORT_REQUIRED


@pytest.mark.parametrize("module", [ModuleId.MARKET_ANALYSIS, ModuleId.EXPERIMENTS])
def test_shared_numerical_diagnostic_is_module_neutral(module, monkeypatch):
    warning = Mock()
    monkeypatch.setattr("app.module_execution.executors.common.log.warning", warning)
    def invalid(raw, _):
        raw["outputs"][0]["text"] = "PRIVATE_UNSUPPORTED 29%"
    with pytest.raises(ExecutorOutputError) as caught:
        run(valid_request(module), invalid)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    warning.assert_called_once_with("Module output rejected module=%s stage=%s rule=%s",
        module.value, "statement_semantics_invalid", "numerical_support_required")


def test_parent_policy_without_parents_fails_closed():
    from app.module_execution import ModuleExecutionContractError
    with pytest.raises(ModuleExecutionContractError):
        support_response_schema(StrategyOutput, ["evd_local"], [],
                                requirement=SupportRequirement.PARENT_REQUIRED)


def test_direct_cmo_emits_generic_floor():
    from tests.test_strategy_intelligence import cmo_facts
    model = IntelligenceModel()
    result = run(request(ModuleId.VIRTUAL_CMO, facts=cmo_facts()), model=model)
    assert all(c.evidence_ids and not c.parent_claim_ids for c in result.normalized_result.claims)
    for definition in model.calls[0]["response_schema"]["$defs"].values():
        if "parent_claim_ids" in definition.get("properties", {}):
            assert definition["properties"]["parent_claim_ids"].get("minItems", 0) == 0
            assert definition["properties"]["parent_claim_ids"]["maxItems"] == 0
