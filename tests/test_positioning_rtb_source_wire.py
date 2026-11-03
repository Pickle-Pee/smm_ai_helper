"""RTB generation must choose an entire actual local product/proof assertion."""
import copy

import pytest
from jsonschema import Draft202012Validator

from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.positioning_support_selection import (
    rtb_source_catalog, support_selection_wire_schema, decode_support_selection_wire, source_assertion_aliases,
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
        original = payload["outputs"]["RTB"]["text"]
        payload["outputs"]["RTB"]["text"] = sourced(text)
        assert not Draft202012Validator(schema).is_valid(payload)
        payload["outputs"]["RTB"]["text"] = original
        payload["outputs"]["category"]["text"] = sourced(text)
        assert Draft202012Validator(schema).is_valid(payload)


@pytest.mark.parametrize("category", ["product_truth", "existing_proof"])
def test_rtb_exact_source_roundtrips_without_punctuation_or_implicit_citation(category):
    f = fixture(("RTB",))
    f[3][0].input_key = category
    f[3][0].value = "Курс длится 6 недель"
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:])
    payload = output((f[0],schema,*f[2:]))
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


def test_quoted_product_and_external_source_use_closed_keys_without_losing_text():
    f = fixture(("RTB", "category"))
    product = 'Клуб "Маяк" проводит занятия.'
    external = 'Карточка сообщает: "группа выходного дня".'
    f[3][0].value = product
    f[3][1].value = external
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:])
    keys = {text: key for key, text in source_assertion_aliases(f[3], ()).items()}
    values = schema["$defs"]["AllowedPositioningSupportedAssertion"]["enum"]
    assert keys[external] in values
    assert keys[product] not in values
    assert all('"' not in value for value in values)
    rtb_keys = schema["$defs"]["AllowedPositioningRTBSourceKey"]["enum"]
    assert rtb_keys == list(rtb_source_catalog(f[3]))
    assert all('"' not in key for key in rtb_keys)

    payload = output((f[0], schema, *f[2:]))
    payload["outputs"]["category"]["text"] = sourced(keys[external])
    before = copy.deepcopy(payload)
    decoded = decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])
    assert payload == before
    assert [row["text"] for row in decoded["outputs"]] == [product, external]
    assert decoded["outputs"][1]["evidence_ids"] == ["evd_000"]
    for rejected in (keys[external], product, "source_unknown"):
        payload["outputs"]["RTB"]["text"] = sourced(rejected)
        with pytest.raises(ModuleExecutionContractError):
            decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])

def test_rtb_wire_rejects_a_separately_selected_primary_even_if_it_is_product_proof():
    f = fixture(("RTB",))
    f[3][1].input_key = "existing_proof"
    f[3][1].value = "A different assertion."
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:])
    payload = output((f[0], schema, *f[2:]))
    payload["outputs"]["RTB"]["primary_support_key"] = "e001"
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])


def test_equal_quotes_keep_both_sources_and_preserve_additional_references():
    f = fixture(("RTB",), ("clm_parent",))
    f[3][1].input_key = "existing_proof"
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:])
    payload = output((f[0], schema, *f[2:]))
    row = payload["outputs"]["RTB"]
    row["evidence_support"]["e002"] = True
    row["parent_support"]["p000"] = True
    catalog = rtb_source_catalog(f[3])
    assert {source["evidence_id"] for source in catalog.values()} == {"evd_000", "evd_001"}
    for key, source in catalog.items():
        row["text"] = sourced(key)
        decoded = decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])
        statement = decoded["outputs"][0]
        assert statement["text"] == source["text"]
        assert statement["evidence_ids"] == [source["evidence_id"], "evd_002"]
        assert statement["parent_claim_ids"] == ["clm_parent"]


@pytest.mark.parametrize("field", ["evidence_id", "evidence_ids"])
def test_rtb_cannot_supply_raw_evidence_identifiers(field):
    f = fixture(("RTB",))
    payload = output(f)
    payload["outputs"]["RTB"][field] = "evd_001"
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])


def test_rtb_key_is_rejected_when_its_source_changes():
    f = fixture(("RTB",))
    payload = output(f)
    f[3][0].value = "A course of 10 weeks"
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])

@pytest.mark.parametrize("name", [
    "value_proposition", "points_of_difference", "positioning_statement", "message_hierarchy",
])
def test_product_source_binds_exact_text_and_evidence_beyond_rtb(name):
    f = fixture((name,))
    f[3][0].value = "No professional equipment is required."
    f[3][1].value = f[3][0].value
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:])
    payload = output((f[0], schema, *f[2:]))
    row = payload["outputs"][name]
    row["text"] = sourced(next(iter(rtb_source_catalog(f[3]))))
    row["evidence_support"] = dict.fromkeys(row["evidence_support"], False)
    before = copy.deepcopy(payload)
    result = decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])
    assert payload == before
    assert result["outputs"][0]["text"] == f[3][0].value
    assert result["outputs"][0]["evidence_ids"] == ["evd_000"]
    for unbound in (sourced(f[3][0].value), qualitative(f[3][0].value)):
        row["text"] = unbound
        with pytest.raises(ModuleExecutionContractError):
            decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])


def test_target_cannot_select_a_bound_product_source():
    f = fixture(("target",))
    payload = output(f)
    payload["outputs"]["target"]["text"] = sourced(next(iter(rtb_source_catalog(f[3]))))
    with pytest.raises(ModuleExecutionContractError):
        decode_support_selection_wire(payload, f[0], PositioningOutput, *f[2:])
