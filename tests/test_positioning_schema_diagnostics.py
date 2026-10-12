"""Schema-only isolation, relaxation semantics, ref equivalence and privacy."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from app.module_execution.executors import PositioningExecutor
from app.module_execution.executors.common import StatementSemanticsError
from app.module_execution.executors.schemas import (
    PositioningOutput, PositioningWithoutJobOutput, PositioningWithoutAlternativeOutput, PositioningWithoutSeedsOutput,
)
from app.module_execution.executors.support_schema import support_response_schema
from app.module_registry import ModuleId
from tools.positioning_diagnostics import capture_request, main, measurement
from tools.positioning_schema_diagnostics import (
    SCHEMA_CASES, SchemaDiagnosticError, inline_refs, nodes, schema_metadata, schema_variants,
)
from tests.test_module_executors import request


@pytest.fixture(params=[PositioningOutput, PositioningWithoutJobOutput, PositioningWithoutAlternativeOutput,
                       PositioningWithoutSeedsOutput], ids=["both-seeds", "no-job", "no-alternative", "no-seeds"])
def schema_type(request):
    return request.param


@pytest.fixture(params=[False, True], ids=["local-only", "with-parents"])
def schema(schema_type, request):
    return support_response_schema(schema_type, ["evd_PRIVATE_SUPPORT"], ["clm_PRIVATE_SUPPORT"] if request.param else [])


def payload(schema):
    return {"model": "gpt-5-mini", "reasoning": {"effort": "low"}, "max_output_tokens": 16000,
        "input": [{"role": "system", "content": "PRIVATE_INSTRUCTIONS"}, {"role": "user", "content": "PRIVATE_BUSINESS"}],
        "text": {"format": {"name": "module_output", "type": "json_schema", "strict": True, "schema": schema}}}


@pytest.mark.parametrize("case", SCHEMA_CASES)
def test_schema_variants_change_only_schema_and_preserve_source(schema, case):
    original = payload(schema)
    before = deepcopy(original)
    candidate = schema_variants(original)[case]
    assert original == before
    changed = candidate["text"]["format"]["schema"] != original["text"]["format"]["schema"]
    if case == "schema_collapse_single_support_anyof" and schema_metadata(schema)["support_allowlist_counts"][1]:
        assert not changed  # Two-branch support ORs are deliberately preserved.
    else:
        assert changed
    actual = deepcopy(candidate)
    actual["text"]["format"]["schema"] = deepcopy(schema)
    assert actual == original  # Includes instructions, context, model, budget, reasoning, strict/name.
    Draft202012Validator.check_schema(candidate["text"]["format"]["schema"])
    assert schema_metadata(candidate["text"]["format"]["schema"])["provider_compatibility"] == "not_verified"
    candidate["text"]["format"]["schema"].clear()
    assert original == before


def statement(**changes):
    return {"outputs": [{"output_name": "differentiation", "text": "Synthetic direction", "kind": "HYPOTHESIS",
        "confidence": "MEDIUM", "evidence_ids": ["evd_PRIVATE_SUPPORT"], "parent_claim_ids": [], **changes}],
        "assumptions": [], "limitations": []}


@pytest.mark.parametrize("case,changes", [
    ("schema_no_support_anyof", {"evidence_ids": [], "parent_claim_ids": []}),
    ("schema_no_string_bounds", {"text": ""}),
    ("schema_no_support_enums", {"evidence_ids": ["evd_unknown"]}),
    ("schema_no_semantic_enums", {"kind": "OBSERVATION"}),
    ("schema_flatten_output_union", {"kind": "OBSERVATION"}),
])
def test_relaxations_have_specific_semantic_witness(schema, case, changes):
    original = Draft202012Validator(schema)
    assert original.is_valid(statement())
    example = statement(**changes)
    assert not original.is_valid(example)
    relaxed = schema_variants(payload(schema))[case]["text"]["format"]["schema"]
    assert Draft202012Validator(relaxed).is_valid(example)


def test_array_bounds_relaxes_cardinality_without_removing_refs_or_union(schema):
    example = statement()
    example["outputs"] *= 33
    assert not Draft202012Validator(schema).is_valid(example)
    relaxed = schema_variants(payload(schema))["schema_no_array_bounds"]["text"]["format"]["schema"]
    assert Draft202012Validator(relaxed).is_valid(example)
    assert schema_metadata(relaxed)["keyword_counts"]["$ref"] == schema_metadata(schema)["keyword_counts"]["$ref"]
    assert schema_metadata(relaxed)["keyword_counts"]["anyOf"] == schema_metadata(schema)["keyword_counts"]["anyOf"]


@pytest.mark.parametrize("case", ["schema_inline_refs", "schema_no_annotations"])
def test_representation_variants_preserve_validation_language(schema, case):
    candidate = schema_variants(payload(schema))[case]["text"]["format"]["schema"]
    baseline_validator = Draft202012Validator(schema)
    candidate_validator = Draft202012Validator(candidate)
    examples = [statement(), statement(evidence_ids=[]), statement(evidence_ids=["bogus"]),
                statement(kind="OBSERVATION"), statement(text=""), statement(output_name="unknown")]
    extra = statement()
    extra["outputs"][0]["extra"] = True
    examples.append(extra)
    for example in examples:
        assert baseline_validator.is_valid(example) == candidate_validator.is_valid(example)


def test_flattened_kind_remains_rejected_by_server_semantics(schema):
    example = statement(kind="OBSERVATION")
    candidate = schema_variants(payload(schema))["schema_flatten_output_union"]["text"]["format"]["schema"]
    assert Draft202012Validator(candidate).is_valid(example)
    with pytest.raises(StatementSemanticsError):
        PositioningExecutor(model_call=None).validate_statement(SimpleNamespace(**example["outputs"][0]), {}, {})


def test_group_boundaries_are_exact(schema):
    matrix = schema_variants(payload(schema))
    for case, keys in (("schema_no_string_bounds", ("minLength", "maxLength")),
                       ("schema_no_array_bounds", ("minItems", "maxItems")),
                       ("schema_no_annotations", ("title", "description", "default", "examples"))):
        expected = deepcopy(schema)
        for node in nodes(expected):
            for key in keys:
                node.pop(key, None)
        assert matrix[case]["text"]["format"]["schema"] == expected
    expected = deepcopy(schema)
    for name in ("AllowedEvidenceId", "AllowedParentClaimId"):
        expected.get("$defs", {}).get(name, {}).pop("enum", None)
    assert matrix["schema_no_support_enums"]["text"]["format"]["schema"] == expected
    assert matrix["schema_flatten_output_union"]["text"]["format"]["schema"]["$defs"] == schema["$defs"]


def test_metadata_does_not_serialize_names_values_or_literals(schema):
    report = schema_metadata(schema)
    assert report["json_schema_valid"] is True
    assert report["required_mismatch_nodes"] == report["additional_properties_mismatch_nodes"] == 0
    assert report["contradictory_length_ranges"] == 0
    assert report["resolved_anyof_depth"] == 2 and report["resolved_container_depth"] == 4
    assert report["support_anyof_nodes"] in (2, 4)
    assert report["type_list_unions"] == 0
    assert "PRIVATE_SUPPORT" not in json.dumps(report)
    literal_schema = {"type": "object", "properties": {"PRIVATE_PROPERTY": {"enum": [{"minLength": "PRIVATE_VALUE"}]}},
                      "required": ["PRIVATE_PROPERTY"], "additionalProperties": False}
    before = deepcopy(literal_schema)
    assert schema_metadata(literal_schema)["keyword_counts"]["minLength"] == 0
    assert "PRIVATE" not in json.dumps(schema_metadata(literal_schema))
    assert literal_schema == before


@pytest.mark.parametrize("schema", [
    {"$ref": "https://PRIVATE_HOST/schema"},
    {"$ref": "#/$defs/missing", "$defs": {}},
    {"$ref": "#/$defs/loop", "$defs": {"loop": {"$ref": "#/$defs/loop"}}},
    {"$ref": "#/$defs/value", "type": "number", "$defs": {"value": {"type": "string"}}},
])
def test_ref_expansion_rejects_remote_cycles_and_conflicting_siblings(schema):
    before = deepcopy(schema)
    with pytest.raises(SchemaDiagnosticError) as caught:
        inline_refs(schema)
    assert "PRIVATE" not in str(caught.value)
    assert schema == before


def test_actual_executor_schema_and_diagnostic_variants_have_stable_baseline():
    replay = asyncio.run(capture_request(request(ModuleId.POSITIONING), model="gpt-5-mini"))
    before = deepcopy(replay.payload)
    matrix = schema_variants(replay.payload)
    assert replay.payload == before
    assert set(matrix) == set(SCHEMA_CASES)
    assert all(measurement(value["input"]) == measurement(before["input"]) for value in matrix.values())


def test_schema_only_rejects_non_schema_live_case_before_reading_snapshot(capsys):
    import logging
    previous = logging.root.manager.disable
    try:
        assert main(["--snapshot", "missing.diagnostic-snapshot.json", "--run-id", "a" * 64, "--job-id", "test",
            "--schema-only", "--live", "--case", "no_core", "--max-calls", "1"]) == 2
        assert capsys.readouterr().out == '{"error":"live_policy_rejected"}\n'
    finally:
        logging.disable(previous)
