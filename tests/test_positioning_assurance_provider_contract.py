"""Simple provider text retains independent canonical assurance validation."""
from jsonschema import Draft202012Validator
from app.module_execution.executors.positioning_support_selection import product_source_catalog
import asyncio
import copy
import pytest
from tests.test_positioning_support_selection import fixture, output, qualitative, sourced, SelectionModel
from app.module_execution.executors.positioning_assurance import ASSURANCE


@pytest.mark.parametrize("text", ["Занятия с опытным мастером.",
    "A guaranteed finished product.", "Professional instruction for beginners."])
def test_unsupported_assurance_passes_syntax_but_fails_actual_canonical_validation(text):
    from tests.test_module_executors import request
    from app.module_registry import ModuleId
    from app.module_execution.executors import PositioningExecutor, ExecutorOutputError
    model = SelectionModel(lambda p,d: p["outputs"]["frame_of_reference"].update(text=qualitative(text)))
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True).execute(
            request(ModuleId.POSITIONING, outputs=("frame_of_reference",))))
    assert len(model.calls) == 1
    assert Draft202012Validator(model.calls[0]["response_schema"]).is_valid(model.last_payload)


def test_canonical_detector_keeps_its_existing_semantics():
    assert ASSURANCE.search("Опытный мастер") and ASSURANCE.search("GUARANTEED result")
    assert not ASSURANCE.search("Новый опыт") and not ASSURANCE.search("inexperienced beginners")


def test_supplied_qualification_without_final_punctuation_can_be_quoted_exactly():
    from dataclasses import replace
    from tests.test_module_executors import facts_for_module, request
    from app.module_registry import ModuleId
    from app.module_execution.executors.positioning import PositioningExecutor
    from tests.test_positioning_support_selection import SelectionModel
    truth = "Занятия проводит опытный мастер"
    facts = tuple(replace(item,value=truth) if item.label=="product_truth" else item
        for item in facts_for_module(ModuleId.POSITIONING))
    invocation = request(ModuleId.POSITIONING, facts=facts, outputs=("offer", "RTB"))
    model = SelectionModel(lambda p,d: p["outputs"]["offer"].update(text=sourced(next(
        key for key, source in d["positioning_product_sources"].items()
        if source["text"] == truth))))
    result = asyncio.run(PositioningExecutor(model_call=model,support_selection_wire=True).execute(invocation))
    assert [row["text"] for row in result.payload["outputs"]] == [truth,truth]
    assert len(model.calls)==1


@pytest.mark.parametrize("cite_message", [False,True])
def test_full_source_enum_cannot_launder_other_category_as_product_qualification(cite_message):
    from dataclasses import replace
    from tests.test_module_executors import facts_for_module, request, fact
    from app.module_registry import ModuleId
    from app.module_execution.executors.positioning import PositioningExecutor
    from app.module_execution.executors import ExecutorOutputError
    from tests.test_positioning_support_selection import SelectionModel
    truth = "Занятия проводит опытный мастер."
    facts = (*facts_for_module(ModuleId.POSITIONING),fact("message",truth))
    def mutate(payload,data):
        row=payload["outputs"]["offer"];row["text"]=sourced(truth)
        if cite_message:
            identity=next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"]=="message")
            alias=next(k for k,v in data["positioning_support_selection_catalog"]["evidence"].items() if v==identity)
            row["evidence_support"][alias]=True
    model=SelectionModel(mutate)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PositioningExecutor(model_call=model,support_selection_wire=True).execute(
            request(ModuleId.POSITIONING,facts=facts,outputs=("offer",))))
    assert len(model.calls)==1
    assert Draft202012Validator(model.calls[0]["response_schema"]).is_valid(model.last_payload)


def test_source_without_punctuation_is_not_repaired_by_the_decoder():
    from app.module_execution.executors.positioning_support_selection import support_selection_wire_schema, decode_support_selection_wire
    from app.module_execution.executors.schemas import PositioningOutput
    f=fixture(("offer",));f[3][0].value="An experienced instructor"
    schema=support_selection_wire_schema(f[0],PositioningOutput,*f[2:])
    payload=output((f[0],schema,*f[2:]));payload["outputs"]["offer"]["text"]=sourced(next(iter(product_source_catalog(f[3]))))
    before=copy.deepcopy(payload)
    decoded=decode_support_selection_wire(payload,f[0],PositioningOutput,*f[2:])
    assert payload==before and decoded["outputs"][0]["text"]==f[3][0].value
