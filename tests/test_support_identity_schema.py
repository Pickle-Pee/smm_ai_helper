"""Exact request-scoped support authority, independent of executor semantics."""
import asyncio
from dataclasses import replace
import json
from unittest.mock import AsyncMock

from jsonschema import Draft202012Validator
import pytest

from app.module_execution import ModuleExecutionContractError, UpstreamExecutionResult
from app.module_execution.executors import PositioningExecutor, ExecutorOutputError
from app.module_execution.executors.common import BaseExecutor, OutputFailureStage, first_party_evidence, plain, scoped_facts
from app.module_execution.executors.schemas import OutputStatement, PositioningOutput
from app.module_execution.executors.support_schema import support_response_schema, MAX_SUPPORT_IDENTITIES
from app.module_registry import ModuleId
from tests.test_module_executors import FakeModel, dispatch, request
from tests.test_strategy_intelligence import IntelligenceModel, cmo_facts, run, upstream


@pytest.mark.parametrize("locals,parents", [(True, False), (False, True), (True, True)])
def test_availability_matrix(locals, parents):
    schema = support_response_schema(PositioningOutput, ["evd_z", "evd_a"] if locals else [],
                                     ["clm_z", "clm_a"] if parents else [])
    assert schema == support_response_schema(PositioningOutput, ["evd_a", "evd_z"] if locals else [],
                                             ["clm_a", "clm_z"] if parents else [])
    validator = Draft202012Validator(schema)
    for evidence, parent, valid in [
        (["evd_a"], [], locals), ([], ["clm_a"], parents), (["evd_z"], ["clm_z"], locals and parents),
        (["evd_invented"], [], False), ([], ["clm_invented"], False), ([], [], False),
        (["evd_invented"], ["clm_a"], False), (["evd_a"], ["clm_invented"], False),
    ]:
        payload = dict(outputs=[dict(output_name="target", text="Synthetic finding", kind="HYPOTHESIS",
            confidence="MEDIUM", evidence_ids=evidence, parent_claim_ids=parent)], assumptions=[], limitations=[])
        assert validator.is_valid(payload) is valid


def test_neither_support_blocks_before_provider():
    model = AsyncMock()
    req = request(ModuleId.POSITIONING, outputs=("target",))
    result = asyncio.run(PositioningExecutor(model_call=model).generate(req, ()))
    assert result.normalized_result.module_status.value == "BLOCKED"
    assert {r.value for r in result.normalized_result.blocking_reasons} == {"MISSING_BLOCKING_INPUT"}
    model.assert_not_awaited()


@pytest.mark.parametrize("field,invented", [("evidence_ids", "evd_PRIVATE"), ("parent_claim_ids", "clm_PRIVATE")])
def test_nonconforming_provider_rejected_by_exact_schema(field, invented, caplog):
    model = FakeModel(lambda payload, _: payload["outputs"][0].update({field: [invented]}))
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(request(ModuleId.POSITIONING, outputs=("target",)), model)
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID
    assert invented not in str(caught.value) + caplog.text
    assert len(model.calls) == 1


@pytest.mark.parametrize("evidence,parents,stage", [
    (["evd_invented"], [], OutputFailureStage.EVIDENCE_REFERENCE_INVALID),
    ([], ["clm_invented"], OutputFailureStage.PARENT_REFERENCE_INVALID),
    ([], [], OutputFailureStage.SUPPORT_MISSING),
])
def test_runtime_defenses_survive_internal_bypass(evidence, parents, stage):
    req = request(ModuleId.POSITIONING, outputs=("target",))
    statement = OutputStatement.model_construct(output_name="target", text="Synthetic finding", kind="HYPOTHESIS",
        confidence="MEDIUM", evidence_ids=evidence, parent_claim_ids=parents)
    output = PositioningOutput.model_construct(outputs=[statement], assumptions=[], limitations=[])
    with pytest.raises(ExecutorOutputError) as caught:
        BaseExecutor.build_result(PositioningExecutor(model_call=None), req, output, (), {})
    assert caught.value.stage is stage


@pytest.mark.parametrize("family", ["local", "parent"])
def test_oversized_allowlist_fails_before_provider(family):
    req = request(ModuleId.POSITIONING, outputs=("target",))
    evidence = first_party_evidence(req, scoped_facts(req))
    parent = dispatch(req)
    prefix = "evd" if family == "local" else "clm"
    ids = [f"{prefix}_{i:04}" for i in range(MAX_SUPPORT_IDENTITIES + 1)]
    if family == "local":
        evidence = tuple(replace(evidence[0], record=replace(evidence[0].record, evidence_id=value)) for value in ids)
    else:
        claims = tuple(replace(parent.normalized_result.claims[0], claim_id=value) for value in ids)
        parent = replace(parent, payload=plain(parent.payload), normalized_result=replace(parent.normalized_result, claims=claims))
        req = replace(req, upstream_results=(UpstreamExecutionResult(producer_node_id="parent", result=parent),))
    model = AsyncMock()
    with pytest.raises(ModuleExecutionContractError, match="bounds"):
        asyncio.run(PositioningExecutor(model_call=model).generate(req, evidence))
    model.assert_not_awaited()


def test_maximum_identity_sets_fit_provider_bounds_without_enum_duplication():
    from app.module_execution.executors.schemas import PositioningWithoutSeedsOutput
    ids = [f"evd_{i:0124}" for i in range(MAX_SUPPORT_IDENTITIES)]
    schema = support_response_schema(PositioningWithoutSeedsOutput, ids, [s.replace("evd", "clm") for s in ids])
    assert schema["$defs"]["AllowedEvidenceId"]["enum"] == ids
    assert schema["$defs"]["AllowedParentClaimId"]["enum"] == [s.replace("evd", "clm") for s in ids]


@pytest.mark.parametrize("bound", ["MAX_SCHEMA_ENUM_VALUES", "MAX_SCHEMA_STRING_CHARACTERS"])
def test_complete_schema_budget_fails_closed(monkeypatch, bound):
    from app.module_execution.executors import support_schema
    monkeypatch.setattr(support_schema, bound, 1)
    with pytest.raises(ModuleExecutionContractError, match="provider bounds"):
        support_response_schema(PositioningOutput, ["evd_valid"], ["clm_valid"])


@pytest.mark.parametrize("invalid", [["evd_valid", 1], [["evd_nested"]], ["x" * 129]])
def test_corrupted_internal_identity_is_a_bounded_contract_error(invalid):
    with pytest.raises(ModuleExecutionContractError, match="bounds"):
        support_response_schema(PositioningOutput, invalid, [])


def test_downstream_schemas_use_only_accepted_predecessor_identities():
    positioning = dispatch(request(ModuleId.POSITIONING))
    model = IntelligenceModel(use_parents=True)
    cmo = run(request(ModuleId.VIRTUAL_CMO, facts=cmo_facts(), upstream=upstream(positioning)), model=model)
    expected = sorted(c.claim_id for c in positioning.normalized_result.claims)
    assert model.calls[0]["response_schema"]["$defs"]["AllowedParentClaimId"]["enum"] == expected
    experiments_model = IntelligenceModel(use_parents=True)
    run(request(ModuleId.EXPERIMENTS, facts=(), upstream=upstream(cmo)), model=experiments_model)
    schema = experiments_model.calls[0]["response_schema"]
    assert schema["$defs"]["AllowedParentClaimId"]["enum"] == sorted(c.claim_id for c in cmo.normalized_result.claims)
    assert "AllowedEvidenceId" not in schema["$defs"]


def assert_production_support_schema(provider):
    """Used at both worker acceptance and real PostgreSQL persistence boundary."""
    call = provider.calls[0]
    data = json.loads(call["input"][1]["content"])
    schema = call["text"]["format"]["schema"]
    assert data["allowed_parent_claim_ids"] == []
    assert data["upstream_results"] == []
    assert schema["$defs"]["AllowedEvidenceId"]["enum"] == sorted(e["evidence_id"] for e in data["local_evidence"])
    assert "AllowedParentClaimId" not in schema["$defs"]
    assert len(provider.invalid_identity_proposals) == 32
    for name, definition in schema["$defs"].items():
        properties = definition.get("properties", {})
        if "evidence_ids" not in properties:
            continue
        assert properties["parent_claim_ids"]["maxItems"] == 0
        assert "enum" not in properties["parent_claim_ids"]["items"]
        assert len(definition["anyOf"]) == 1
        assert definition["anyOf"][0]["properties"]["evidence_ids"]["minItems"] == 1
        def literal(field):
            return field.get("const") or field["enum"][0]
        statement = dict(output_name=literal(properties["output_name"]), text="Synthetic finding",
            kind="HYPOTHESIS", confidence="MEDIUM", evidence_ids=[data["local_evidence"][0]["evidence_id"]], parent_claim_ids=[])
        validator = Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{name}"})
        assert validator.is_valid(statement)
        assert not validator.is_valid({**statement, "parent_claim_ids": ["clm_invented"]})
        assert not validator.is_valid({**statement, "evidence_ids": ["evd_invented"]})
        assert not validator.is_valid({**statement, "evidence_ids": []})
