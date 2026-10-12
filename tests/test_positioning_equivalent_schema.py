"""Acceptance equivalence and fail-closed proof for single support anyOf."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from app.module_execution.executors.schemas import (
    PositioningOutput, PositioningWithoutJobOutput, PositioningWithoutAlternativeOutput, PositioningWithoutSeedsOutput,
)
from app.module_execution.executors.support_schema import support_response_schema
from tools.positioning_schema_diagnostics import (
    SchemaDiagnosticError, collapse_single_support_anyof, schema_metadata, schema_variants,
)
from tests.test_positioning_schema_diagnostics import payload


CASE = "schema_collapse_single_support_anyof"
EVIDENCE = ["evd_" + f"{index:048x}" for index in range(13)]
PARENT = "clm_" + "1" * 48


@pytest.fixture(params=[PositioningOutput, PositioningWithoutJobOutput, PositioningWithoutAlternativeOutput,
                       PositioningWithoutSeedsOutput], ids=["both-seeds", "no-job", "no-alternative", "no-seeds"])
def schema_type(request):
    return request.param


@pytest.fixture(params=[False, True], ids=["13-local-0-parent", "13-local-with-parent"])
def original_schema(schema_type, request):
    return support_response_schema(schema_type, EVIDENCE, [PARENT] if request.param else [])


def output(**changes):
    return {"outputs": [{"output_name": "differentiation", "kind": "HYPOTHESIS", "text": "Synthetic finding",
        "confidence": "MEDIUM", "evidence_ids": [EVIDENCE[0]], "parent_claim_ids": [], **changes}],
        "assumptions": [], "limitations": []}


def examples():
    yield True, output()
    yield True, output(text="x" * 4000, evidence_ids=EVIDENCE + [EVIDENCE[0]] * 19)
    yield False, output(evidence_ids=[], parent_claim_ids=[])
    yield False, output(evidence_ids=["evd_unknown"])
    yield False, output(parent_claim_ids=["clm_unknown"])
    yield False, output(kind="OBSERVATION")
    yield False, output(kind="unsupported")
    yield False, output(output_name="unknown")
    yield False, output(confidence="VERY_HIGH")
    yield False, output(text="")
    yield False, output(text="x" * 4001)
    yield False, output(evidence_ids=[""])
    yield False, output(evidence_ids=["x" * 129])
    yield False, output(evidence_ids=[EVIDENCE[0]] * 33)
    yield False, output(parent_claim_ids=[PARENT] * 33)
    yield False, output(parent_claim_ids=[""])
    extra = output()
    extra["outputs"][0]["extra"] = True
    yield False, extra
    extra_root = output()
    extra_root["extra"] = True
    yield False, extra_root
    missing = output()
    del missing["outputs"][0]["evidence_ids"]
    yield False, missing
    missing_root = output()
    del missing_root["limitations"]
    yield False, missing_root
    empty_outputs = output()
    empty_outputs["outputs"] = []
    yield False, empty_outputs
    excessive_outputs = output()
    excessive_outputs["outputs"] *= 33
    yield False, excessive_outputs
    too_many_limits = output()
    too_many_limits["limitations"] = ["Limitation"] * 13
    yield False, too_many_limits
    too_many_assumptions = output()
    too_many_assumptions["assumptions"] = ["Assumption"] * 13
    yield False, too_many_assumptions
    empty_assumption = output()
    empty_assumption["assumptions"] = [""]
    yield False, empty_assumption


def test_same_acceptance_language_on_valid_and_invalid_examples(original_schema):
    transformed = collapse_single_support_anyof(original_schema)
    before, after = Draft202012Validator(original_schema), Draft202012Validator(transformed)
    for expected, example in examples():
        assert before.is_valid(example) is expected
        assert after.is_valid(example) is expected
    with_parents = schema_metadata(original_schema)["support_allowlist_counts"][1] > 0
    for example in (output(evidence_ids=[], parent_claim_ids=[PARENT]), output(parent_claim_ids=[PARENT])):
        assert before.is_valid(example) is with_parents
        assert after.is_valid(example) is with_parents
    # Missing strategic seeds must still force their corresponding kinds.
    for name in ("category", "JTBD_frame"):
        for kind in ("HYPOTHESIS", "OBSERVATION", "RECOMMENDATION"):
            example = output(output_name=name, kind=kind)
            assert before.is_valid(example) == after.is_valid(example)


def test_preserves_every_constraint_and_only_promotes_support_floor(original_schema):
    original = deepcopy(original_schema)
    candidate = collapse_single_support_anyof(original_schema)
    assert original_schema == original
    parent_count = schema_metadata(original)["support_allowlist_counts"][1]
    if parent_count:
        assert candidate == original
    else:
        expected = deepcopy(original)
        for definition in expected["$defs"].values():
            if "anyOf" not in definition:
                continue
            branch = definition.pop("anyOf")[0]
            definition["properties"]["evidence_ids"]["minItems"] = 1
            assert branch["properties"]["evidence_ids"]["minItems"] == 1
        assert candidate == expected  # Includes every enum, ref, bound, required and closed-object rule.
        for definition in candidate["$defs"].values():
            if "evidence_ids" in definition.get("properties", {}):
                assert definition["properties"]["evidence_ids"]["minItems"] == 1
                assert definition["properties"]["parent_claim_ids"]["maxItems"] == 0
    assert collapse_single_support_anyof(candidate) == candidate  # Idempotent.


def test_variant_preserves_all_non_schema_payload_fields(original_schema):
    baseline = payload(original_schema)
    before = deepcopy(baseline)
    matrix = schema_variants(baseline)
    candidate = deepcopy(matrix[CASE])
    assert candidate["text"]["format"]["schema"] == collapse_single_support_anyof(original_schema)
    candidate["text"]["format"]["schema"] = deepcopy(original_schema)
    assert candidate == baseline == before
    matrix[CASE]["text"]["format"]["schema"].clear()
    assert baseline == before and matrix["schema_no_support_anyof"]["text"]["format"]["schema"]
    assert "evd_" not in json.dumps(schema_metadata(original_schema))


@pytest.mark.parametrize("corruption", ["enum", "bound", "required", "open_object", "extra_keyword",
    "ref", "boolean_vs_integer", "scope", "unevaluated"])
def test_refuses_unproved_differences_without_mutating_input(corruption):
    schema = support_response_schema(PositioningWithoutSeedsOutput, EVIDENCE, [])
    targets = [definition for definition in schema["$defs"].values() if "anyOf" in definition]
    # Corrupt the last target: earlier transforms on the private copy must not
    # leak partial results when proof of a later target fails.
    target = targets[-1]
    branch = target["anyOf"][0]
    if corruption == "enum": branch["properties"]["confidence"]["enum"] = ["UNKNOWN"]
    if corruption == "bound": branch["properties"]["text"]["maxLength"] = 99
    if corruption == "required": branch["required"].remove("text")
    if corruption == "open_object": branch["additionalProperties"] = True
    if corruption == "extra_keyword": branch["allOf"] = [{"type": "object"}]
    if corruption == "ref": branch["properties"]["evidence_ids"]["items"]["$ref"] = "#/$defs/missing"
    if corruption == "boolean_vs_integer":
        target["properties"]["text"] = {"enum": [True]}
        branch["properties"]["text"] = {"enum": [1]}
    if corruption == "scope":
        target["properties"]["text"]["$id"] = "https://PRIVATE.invalid/text"
        branch["properties"]["text"]["$id"] = "https://PRIVATE.invalid/text"
    if corruption == "unevaluated":
        target["properties"]["text"]["unevaluatedProperties"] = False
        branch["properties"]["text"]["unevaluatedProperties"] = False
    original = deepcopy(schema)
    with pytest.raises(SchemaDiagnosticError) as caught:
        collapse_single_support_anyof(schema)
    assert str(caught.value) == "single_support_anyof_not_equivalent"
    assert schema == original


def test_stronger_parent_floor_is_preserved():
    schema = support_response_schema(PositioningOutput, EVIDENCE, [])
    for definition in schema["$defs"].values():
        if "anyOf" in definition:
            definition["properties"]["evidence_ids"]["minItems"] = 2
    candidate = collapse_single_support_anyof(schema)
    for example in (output(), output(evidence_ids=EVIDENCE[:2])):
        assert Draft202012Validator(schema).is_valid(example) == Draft202012Validator(candidate).is_valid(example)
    assert not Draft202012Validator(candidate).is_valid(output())


def test_preserves_unrelated_single_anyof_and_literal_objects():
    schema = support_response_schema(PositioningOutput, EVIDENCE, [])
    schema["properties"]["unrelated"] = {"anyOf": [{"type": "string"}]}
    schema["required"].append("unrelated")
    schema["properties"]["literal"] = {"enum": [{"anyOf": [{"properties": {"evidence_ids": {}, "parent_claim_ids": {}}}]}]}
    schema["required"].append("literal")
    candidate = collapse_single_support_anyof(schema)
    assert candidate["properties"]["unrelated"] == schema["properties"]["unrelated"]
    assert candidate["properties"]["literal"] == schema["properties"]["literal"]
