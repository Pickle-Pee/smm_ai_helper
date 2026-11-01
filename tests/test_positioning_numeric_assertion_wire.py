"""Provider text alternatives preserve exact supplied numerical assertions."""
import copy
import asyncio
import pytest
from jsonschema import Draft202012Validator

from tests.test_positioning_support_selection import fixture, output
from app.module_execution.executors.positioning_support_selection import support_selection_wire_schema
from app.module_execution.executors.schemas import PositioningOutput
from app.module_execution.executors import PositioningExecutor, ExecutorOutputError
from tests.test_positioning_support_selection import SelectionModel
from tests.test_positioning_numeric_grounding import course_request, COURSE_TRUTH


def test_provider_does_not_allow_paraphrased_digit_quantities():
    f = fixture(("offer",))
    value = output(f)
    value["outputs"]["offer"]["text"] = "A course lasting 6 weeks."
    assert not Draft202012Validator(f[1]).is_valid(value)


def test_exact_supplied_numeric_assertion_has_an_explicit_generation_alternative():
    f = fixture(("offer",))
    evidence = f[3]
    evidence[0].value = "Длительность курса — 6 недель; включена письменная обратная связь."
    before = copy.deepcopy(evidence[0].value)
    schema = support_selection_wire_schema(f[0], PositioningOutput, f[2], evidence, f[4])
    value = output((f[0], schema, f[2], evidence, f[4]))
    value["outputs"]["offer"]["text"] = before
    assert Draft202012Validator(schema).is_valid(value)
    assert evidence[0].value == before
    # The supplied assertion must be represented, not merely admitted as free text.
    assert any(before in definition.get("enum", []) for definition in schema["$defs"].values())


def test_actual_executor_accepts_exact_course_duration_with_its_actual_source():
    model = SelectionModel(lambda p, d: p["outputs"]["offer"].update(text=COURSE_TRUTH))
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True).execute(course_request("offer")))
    assert result.payload["outputs"][0]["text"] == COURSE_TRUTH and len(model.calls) == 1


@pytest.mark.parametrize("text", ["Онлайн-курс длится шесть недель с обратной связью.",
    "A course lasting ٦ weeks."])
def test_portable_ascii_pattern_does_not_replace_full_word_or_unicode_number_validation(text):
    # These can enter the qualitative provider branch; the original strict guard
    # must still reject them rather than respelling, filtering or repairing them.
    model = SelectionModel(lambda p, d: p["outputs"]["offer"].update(text=text))
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True).execute(course_request("offer")))
    assert len(model.calls) == 1


def test_global_numeric_enum_does_not_authorize_an_uncited_source():
    from dataclasses import replace
    from tests.test_module_executors import fact
    invocation = course_request("offer")
    packet = replace(invocation.context_packet, known_facts=(*invocation.context_packet.known_facts,
        fact("message", "Budget 10 dollars.")))
    invocation = replace(invocation, context_packet=packet)
    model = SelectionModel(lambda p, d: p["outputs"]["offer"].update(text="Budget 10 dollars."))
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True).execute(invocation))
    assert len(model.calls) == 1


def test_parent_assertions_have_explicit_choices_without_becoming_implicit_citations():
    f = fixture(("category",), ("clm_parent",))
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:], parent_assertions=("A 6 week course.",))
    value = output((f[0], schema, *f[2:]))
    value["outputs"]["category"]["text"] = "A 6 week course."
    assert Draft202012Validator(schema).is_valid(value)
    from app.module_execution.executors.positioning_support_selection import decode_support_selection_wire
    decoded = decode_support_selection_wire(value, f[0], PositioningOutput, *f[2:], parent_assertions=("A 6 week course.",))
    assert decoded["outputs"][0]["parent_claim_ids"] == []


def test_long_sources_are_not_truncated_into_new_numeric_assertions():
    f = fixture(("offer",))
    f[3][0].value = "6 " + "x" * 4000
    schema = support_selection_wire_schema(f[0], PositioningOutput, *f[2:])
    assert not any(definition.get("enum") for name, definition in schema["$defs"].items()
        if name == "AllowedPositioningNumericAssertion")
    assert len(schema["$defs"]["PositioningEvidenceSelection"]["properties"]) == len(f[3])
