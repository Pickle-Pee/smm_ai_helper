"""RTB generation must choose an entire actual local product/proof assertion."""
import copy

import pytest
from jsonschema import Draft202012Validator

from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.positioning_support_selection import (
    support_selection_wire_schema, decode_support_selection_wire,
)
from app.module_execution.executors.schemas import PositioningOutput
from tests.test_positioning_support_selection import fixture, output, qualitative, sourced


def test_rtb_cannot_choose_qualitative_paraphrase_even_when_other_outputs_can():
    f = fixture(("RTB", "offer"))
    payload = output(f)
    payload["outputs"]["RTB"]["text"] = qualitative("Materials and firing included.")
    assert not Draft202012Validator(f[1]).is_valid(payload)


def test_rtb_source_enum_cannot_offer_other_context_or_parent_as_product_proof():
    f = fixture(("RTB", "category"), ("clm_parent",))
    f[3][1].value = "An unsupported promise from another category."
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:],
        parent_assertions=("A parent assertion.",))
    for text in (f[3][1].value, "A parent assertion."):
        payload = output((f[0],schema,*f[2:]))
        payload["outputs"]["RTB"]["text"] = sourced(text)
        assert not Draft202012Validator(schema).is_valid(payload)
        payload["outputs"]["RTB"]["text"] = sourced(f[3][0].value)
        payload["outputs"]["category"]["text"] = sourced(text)
        assert Draft202012Validator(schema).is_valid(payload)


@pytest.mark.parametrize("category", ["product_truth", "existing_proof"])
def test_rtb_exact_source_roundtrips_without_punctuation_or_implicit_citation(category):
    f = fixture(("RTB",))
    f[3][0].input_key = category
    f[3][0].value = "Курс длится 6 недель"
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:])
    payload = output((f[0],schema,*f[2:]))
    payload["outputs"]["RTB"]["text"] = sourced(f[3][0].value)
    before = copy.deepcopy(payload)
    result = decode_support_selection_wire(payload,f[0],PositioningOutput,*f[2:])
    assert payload == before
    assert result["outputs"][0]["text"] == f[3][0].value
    assert result["outputs"][0]["evidence_ids"] == ["evd_000"]


@pytest.mark.parametrize("value", ["", "6 " + "x" * 4000])
def test_missing_bounded_rtb_assertion_fails_before_generation_without_truncation(value):
    f = fixture(("offer",), count=1)
    f[3][0].value = value
    before = copy.deepcopy(f[3][0].value)
    with pytest.raises(ModuleExecutionContractError):
        support_selection_wire_schema(f[0],PositioningOutput,("RTB",),f[3],f[4])
    assert f[3][0].value == before
