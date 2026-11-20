"""Provider grammar simplification must preserve the original acceptance language."""
from copy import deepcopy
import itertools

from jsonschema import Draft202012Validator
import pytest

from app.module_execution.executors.intelligence_schemas import StrategyOutput
from app.module_execution.executors.provider_schema import (
    SchemaProjectionError, collapse_redundant_support_anyof, nodes,
)
from app.module_execution.executors.support_schema import support_response_schema, SupportRequirement

EVIDENCE = ["evd_" + str(i) for i in range(6)]
PARENTS = ["clm_" + str(i) for i in range(16)]


def schema(requirement=SupportRequirement.PARENT_REQUIRED):
    return support_response_schema(StrategyOutput, EVIDENCE, PARENTS, requirement=requirement)


def example(**changes):
    return {"outputs": [{"output_name": "main_growth_constraint", "kind": "HYPOTHESIS",
        "text": "Validate qualified demand", "items": ["Interview prospective customers"],
        "numeric_context": [], "confidence": "MEDIUM", "evidence_ids": [],
        "parent_claim_ids": [PARENTS[0]], **changes}], "assumptions": [], "limitations": []}


def test_original_and_projection_accept_same_valid_and_invalid_outputs():
    original = schema()
    projected = collapse_redundant_support_anyof(original)
    before, after = Draft202012Validator(original), Draft202012Validator(projected)
    valid = invalid = 0
    for name, kind, evidence, parents in itertools.product(
            ("main_growth_constraint", "strategic_diagnosis", "unknown"),
            ("HYPOTHESIS", "RECOMMENDATION", "OBSERVATION"),
            ([], EVIDENCE[:1], ["evd_unknown"], EVIDENCE[:1] * 33),
            ([], PARENTS[:1], ["clm_unknown"], PARENTS[:1] * 33)):
        value = example(output_name=name, kind=kind, evidence_ids=evidence, parent_claim_ids=parents)
        accepted = before.is_valid(value)
        assert after.is_valid(value) is accepted
        valid += accepted
        invalid += not accepted
    assert valid and invalid
    for changes in ({"items": []}, {"items": ["a", "b"]}, {"text": ""},
            {"text": "x" * 4001}, {"extra": True},
            {"numeric_context": [{"support_id": "unknown", "quote": "Supplied quote"}]},
            {"numeric_context": [{"support_id": EVIDENCE[0], "quote": "x" * 1001}]},
            {"numeric_context": [{"support_id": EVIDENCE[0], "quote": "Supplied 42 seats"}]}):
        value = example(**changes)
        assert before.is_valid(value) == after.is_valid(value)


def test_projection_only_removes_two_redundant_or_nodes_and_keeps_all_constraints():
    original = schema(); saved = deepcopy(original)
    projected = collapse_redundant_support_anyof(original)
    expected = deepcopy(original)
    for name in ("MainGrowthConstraintStatement", "OtherStrategyStatement"):
        expected["$defs"][name].pop("anyOf")
        assert projected["$defs"][name]["properties"]["parent_claim_ids"]["minItems"] == 1
    assert projected == expected
    assert original == saved
    assert collapse_redundant_support_anyof(projected) == projected
    assert sum("anyOf" in n for n in nodes(original)) - sum("anyOf" in n for n in nodes(projected)) == 2


def test_evidence_or_parent_without_required_parent_must_keep_its_or():
    original = schema(SupportRequirement.ANY)
    projected = collapse_redundant_support_anyof(original)
    assert projected == original
    assert not Draft202012Validator(projected).is_valid(example(parent_claim_ids=[]))


def test_different_branch_constraint_is_never_discarded_without_witness():
    original = schema()
    for definition in ("MainGrowthConstraintStatement", "OtherStrategyStatement"):
        original["$defs"][definition]["anyOf"][1]["properties"]["text"]["maxLength"] = 2
    projected = collapse_redundant_support_anyof(original)
    assert projected == original


@pytest.mark.parametrize("keyword", ["$id", "$anchor", "$dynamicAnchor", "$dynamicRef",
                                   "unevaluatedProperties", "unevaluatedItems"])
def test_scope_dependent_proof_is_refused(keyword):
    original = schema()
    original[keyword] = False if keyword.startswith("unevaluated") else "https://scope.invalid/"
    saved = deepcopy(original)
    with pytest.raises(SchemaProjectionError):
        collapse_redundant_support_anyof(original)
    assert original == saved


@pytest.mark.parametrize("ref", ["#/$defs/MainGrowthConstraintStatement/anyOf/0/properties/text",
                                 "https://external.invalid/schema", "#/$defs/missing"])
def test_references_that_cannot_survive_subtree_removal_are_refused(ref):
    original = schema()
    original["$defs"]["NumericContext"]["properties"]["quote"] = {"$ref": ref}
    with pytest.raises(SchemaProjectionError):
        collapse_redundant_support_anyof(original)


def test_json_boolean_does_not_supply_an_integer_witness():
    original = schema()
    for definition in ("MainGrowthConstraintStatement", "OtherStrategyStatement"):
        d = original["$defs"][definition]
        d["properties"]["text"] = {"enum": [True]}
        for branch in d["anyOf"]:
            branch["properties"]["text"] = {"enum": [1]}
    assert collapse_redundant_support_anyof(original) == original


def test_provider_schema_mutation_cannot_weaken_original_executor_validation():
    import asyncio
    import json
    from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
    from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage
    from tests.test_virtual_cmo_diagnostics import restored
    from tests.test_strategy_builder import StrategyModel

    request = restored()
    calls = []

    async def malicious_model(**kwargs):
        schema = kwargs["response_schema"]
        assert "anyOf" not in schema["$defs"]["MainGrowthConstraintStatement"]
        assert schema["$defs"]["MainGrowthConstraintStatement"]["properties"]["parent_claim_ids"]["minItems"] == 1
        output = json.loads(await StrategyModel(use_parents=True)(**kwargs))
        # A provider can ignore/mutate its own schema. The original local
        # validator must still reject the missing strategic parent.
        output["outputs"][0]["parent_claim_ids"] = []
        schema.clear()
        calls.append(True)
        return json.dumps(output)

    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=malicious_model).execute(request))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID
    assert calls == [True]
