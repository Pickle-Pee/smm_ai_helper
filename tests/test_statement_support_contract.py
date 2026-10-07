"""Common support floor in actual emitted schemas and the selected parsers."""
import json

from jsonschema import Draft202012Validator
from pydantic import ValidationError
import pytest

from app.module_execution.executors import ExecutorOutputError, PositioningExecutor
from app.module_execution.executors import schemas, intelligence_schemas
from app.module_execution.executors.common import BaseExecutor, OutputFailureStage
from app.module_registry import ModuleId
from tests.test_module_executors import FakeModel, dispatch, request as invocation
from tests.test_positioning_seed_contract import seed_request
from tests.test_strategy_intelligence import IntelligenceModel, run, valid_request


@pytest.fixture(params=["competitor", "creator", "market", "cmo", "experiments",
                       "positioning", "without-job", "without-alternative", "without-seeds"])
def emitted_contract(request):
    """Capture the schema passed by real executors to their model boundary."""
    name = request.param
    if name in {"market", "cmo", "experiments"}:
        module = {"market": ModuleId.MARKET_ANALYSIS, "cmo": ModuleId.VIRTUAL_CMO,
                  "experiments": ModuleId.EXPERIMENTS}[name]
        model = IntelligenceModel(use_parents=True)
        run(valid_request(module), model=model)
    else:
        model = FakeModel()
        if name in {"competitor", "creator"}:
            module = {"competitor": ModuleId.COMPETITOR_ANALYSIS, "creator": ModuleId.CREATOR}[name]
            req = invocation(module)
        else:
            req = seed_request(name not in {"without-job", "without-seeds"},
                               name not in {"without-alternative", "without-seeds"})
        dispatch(req, model)
    assert len(model.calls) == 1
    return model.calls[0]["response_schema"]


@pytest.mark.parametrize("local,parent", [(True, False), (False, True), (True, True), (False, False)])
def test_every_emitted_statement_schema_and_parser_agree(emitted_contract, local, parent):
    schema = emitted_contract
    Draft202012Validator.check_schema(schema)
    checked = 0
    for name, definition in schema["$defs"].items():
        if "evidence_ids" not in definition.get("properties", {}):
            continue
        statement_type = getattr(schemas, name, None) or getattr(intelligence_schemas, name)
        properties = definition["properties"]
        def literal(field):
            return field["const"] if "const" in field else field["enum"][0]
        payload = dict(output_name=literal(properties["output_name"]), text="Synthetic finding",
                       kind=literal(properties["kind"]), confidence="MEDIUM",
                       evidence_ids=[schema["$defs"].get("AllowedEvidenceId", {"enum": ["evd_unavailable"]})["enum"][0]] if local else [],
                       parent_claim_ids=[schema["$defs"].get("AllowedParentClaimId", {"enum": ["clm_unavailable"]})["enum"][0]] if parent else [])
        if "items" in properties:
            payload["items"] = ["Synthetic priority"]
        validator = Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{name}"})
        available_local = "AllowedEvidenceId" in schema["$defs"]
        available_parent = "AllowedParentClaimId" in schema["$defs"]
        assert validator.is_valid(payload) is ((local or parent) and (not local or available_local)
                                                and (not parent or available_parent))
        if local or parent:
            assert statement_type.model_validate_json(json.dumps(payload)).model_dump() == payload
        else:
            with pytest.raises(ValidationError):
                statement_type.model_validate_json(json.dumps(payload))
        # Strict-compatible anyOf objects preserve all inherited constraints.
        supports = [field for field, available in (("evidence_ids", available_local),
                                                  ("parent_claim_ids", available_parent)) if available]
        assert len(definition["anyOf"]) == len(supports)
        for branch, support in zip(definition["anyOf"], supports):
            assert branch["additionalProperties"] is False
            assert set(branch["required"]) == set(properties)
            assert branch["properties"][support]["minItems"] == 1
            for field, available in (("evidence_ids", available_local), ("parent_claim_ids", available_parent)):
                assert branch["properties"][field]["maxItems"] == (32 if available else 0)
        checked += 1
    assert checked


def test_common_base_support_floor_and_deterministic_schema():
    assert schemas.OutputStatement.model_json_schema() == schemas.OutputStatement.model_json_schema()
    with pytest.raises(ValidationError):
        schemas.OutputStatement(output_name="output", text="Synthetic finding", kind="HYPOTHESIS",
                                confidence="MEDIUM", evidence_ids=[], parent_claim_ids=[])


def test_runtime_support_missing_survives_explicit_validation_bypass():
    req = invocation(ModuleId.POSITIONING, outputs=("target",))
    statement = schemas.OutputStatement.model_construct(output_name="target", text="Synthetic finding",
        kind="HYPOTHESIS", confidence="MEDIUM", evidence_ids=[], parent_claim_ids=[])
    output = schemas.PositioningOutput.model_construct(outputs=[statement], assumptions=[], limitations=[])
    with pytest.raises(ExecutorOutputError) as caught:
        BaseExecutor.build_result(PositioningExecutor(model_call=None), req, output, (), {})
    assert caught.value.stage is OutputFailureStage.SUPPORT_MISSING


@pytest.mark.parametrize("name", ["RTB", "value_proposition", "positioning_statement", "offer"])
def test_positioning_parent_only_cannot_replace_local_product_truth(name):
    from app.module_execution import UpstreamExecutionResult
    parent = dispatch(invocation(ModuleId.POSITIONING))
    req = invocation(ModuleId.POSITIONING, outputs=(name,), upstream=(
        UpstreamExecutionResult(producer_node_id="parent", result=parent),))
    model = FakeModel(lambda payload, data: payload["outputs"][0].update(
        evidence_ids=[], parent_claim_ids=[data["allowed_parent_claim_ids"][0]]))
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(req, model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


@pytest.mark.parametrize("module", [ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS])
def test_parent_only_intelligence_remains_valid_but_missing_lineage_fails(module):
    req = valid_request(module)
    result = run(req, lambda raw, _: [s.update(evidence_ids=[]) for s in raw["outputs"]])
    assert all(c.parent_claim_ids and not c.evidence_ids for c in result.normalized_result.claims)
    def omit_parent(raw, data):
        raw["outputs"][0].update(parent_claim_ids=[], evidence_ids=[data["local_evidence"][0]["evidence_id"]])
    # EXPERIMENTS also has local context in this variant; its strategic parent
    # rule must reject evidence-only even though the generic floor accepts it.
    if module is ModuleId.EXPERIMENTS:
        from dataclasses import replace
        from tests.test_module_executors import fact
        req = replace(req, context_packet=replace(req.context_packet, known_facts=(fact("business_goal"),)))
    with pytest.raises(ExecutorOutputError) as caught:
        run(req, omit_parent)
    assert caught.value.stage is (OutputFailureStage.STATEMENT_SEMANTICS_INVALID
        if module is ModuleId.VIRTUAL_CMO else OutputFailureStage.RESULT_CONTRACT_INVALID)
