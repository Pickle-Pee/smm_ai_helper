"""Text alternatives have explicit disjoint modes and preserve literal values."""
import copy

import pytest
from jsonschema import Draft202012Validator

from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.positioning_support_selection import (
    decode_support_selection_wire, product_source_catalog, support_selection_wire_schema,
)
from app.module_execution.executors.schemas import PositioningOutput
from tests.test_positioning_support_selection import fixture, output


@pytest.mark.parametrize("mode,text", [
    ("QUALITATIVE", "A qualitative direction to validate."),
    ("SOURCE", "Materials and firing included."),
])
def test_explicit_text_mode_roundtrips_without_changing_raw_or_canonical(mode, text):
    f = fixture(("offer",))
    payload = output(f)
    payload["outputs"]["offer"]["text"] = {"mode": mode, "value": next(iter(product_source_catalog(f[3]))) if mode == "SOURCE" else text}
    before = copy.deepcopy(payload)
    assert Draft202012Validator(f[1]).is_valid(payload)
    result = decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])
    assert payload == before
    assert result["outputs"][0]["text"] == text
    assert Draft202012Validator(f[0]).is_valid(result)


@pytest.mark.parametrize("selection", [
    {"mode": "SOURCE", "value": "Invented source."},
        {"mode": "SOURCE", "value": "Materials and firing included.", "extra": True},
    {"mode": "UNKNOWN", "value": "A qualitative direction."},
    {"value": "A qualitative direction."},
    "Materials and firing included.",
])
def test_modes_fail_closed_without_guessing_or_repair(selection):
    f = fixture(("offer",))
    payload = output(f)
    payload["outputs"]["offer"]["text"] = selection
    before = copy.deepcopy(payload)
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])
    assert payload == before


def test_source_mode_preserves_provided_numeric_wording_without_punctuation():
    f = fixture(("offer",))
    f[3][0].value = "Курс длится 6 недель"
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:])
    payload = output((f[0], schema, *f[2:]))
    payload["outputs"]["offer"]["text"] = {"mode": "SOURCE", "value": next(iter(product_source_catalog(f[3])))}
    result = decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])
    assert result["outputs"][0]["text"] == f[3][0].value


def test_text_union_is_over_disjoint_tagged_objects_not_over_strings():
    f = fixture(("offer",))
    defs = f[1]["$defs"]
    row = defs[f[1]["properties"]["outputs"]["properties"]["offer"]["$ref"].split("/")[-1]]
    text = defs[row["properties"]["text"]["$ref"].split("/")[-1]]
    branches = [defs[b["$ref"].split("/")[-1]] for b in text["anyOf"]]
    assert all(b["type"] == "object" and b["additionalProperties"] is False for b in branches)
    assert [b["properties"]["mode"]["enum"] for b in branches] == [["QUALITATIVE"], ["SOURCE"]]
    assert all(set(b["required"]) == {"mode", "value"} for b in branches)


@pytest.mark.parametrize("version", ["v3", "v5"])
def test_old_wire_is_not_silently_reinterpreted(version):
    f = fixture(("offer",))
    payload = output(f)
    payload["wire_contract_version"] = f"positioning.support_selection.{version}"
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])


def test_source_mode_is_absent_when_no_complete_bounded_source_exists():
    f = fixture(("offer",), count=1)
    f[3][0].value = "x" * 4001
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:])
    payload = output((f[0], schema, *f[2:]))
    payload["outputs"]["offer"]["text"] = {"mode": "QUALITATIVE", "value": "A direction to validate."}
    assert Draft202012Validator(schema).is_valid(payload)
    payload["outputs"]["offer"]["text"]["mode"] = "SOURCE"
    assert not Draft202012Validator(schema).is_valid(payload)
