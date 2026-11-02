"""Word quantities retain independent canonical validation and literal sources."""
import pytest
import asyncio
from jsonschema import Draft202012Validator
from tests.test_positioning_support_selection import fixture, output, qualitative, sourced, SelectionModel


@pytest.mark.parametrize("text", ["Материалы и обжиг в одном занятии.",
    "A course lasting six weeks.", "A single introductory session."])
def test_unsupported_word_quantities_pass_syntax_but_fail_actual_canonical_validation(text):
    from app.module_execution.executors import PositioningExecutor, ExecutorOutputError
    from tests.test_positioning_numeric_grounding import course_request
    model = SelectionModel(lambda p,d: p['outputs']['offer'].update(text=qualitative(text)))
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PositioningExecutor(model_call=model,support_selection_wire=True).execute(course_request('offer')))
    assert len(model.calls)==1
    assert Draft202012Validator(model.calls[0]['response_schema']).is_valid(model.last_payload)


@pytest.mark.parametrize("text", ["Однако вывод требует проверки.", "Стоимость неизвестна.",
    "Статья о процессе занятия.", "Триггер записи требует проверки.", "Consider oneself a beginner."])
def test_ordinary_words_are_not_excluded_by_a_cardinal_prefix(text):
    f=fixture(('offer',));payload=output(f);payload['outputs']['offer']['text']=qualitative(text)
    assert Draft202012Validator(f[1]).is_valid(payload)


@pytest.mark.parametrize("truth", ["Стоимость неизвестна.", "Однако вывод требует проверки."])
def test_complete_source_assertion_preserves_conservatively_excluded_words(truth):
    f=fixture(('offer',));f[3][0].value=truth
    from app.module_execution.executors.positioning_support_selection import support_selection_wire_schema
    from app.module_execution.executors.schemas import PositioningOutput
    schema=support_selection_wire_schema(f[0],PositioningOutput,*f[2:])
    value=output((f[0],schema,*f[2:]));value['outputs']['offer']['text']=sourced(truth)
    assert Draft202012Validator(schema).is_valid(value)


@pytest.mark.parametrize("truth", ["Курс длится шесть недель.", "Курс длится 6 недель."])
def test_actual_supplied_word_or_digit_quantity_remains_an_exact_literal_choice(truth):
    from dataclasses import replace
    from tests.test_module_executors import facts_for_module,request
    from tests.test_positioning_support_selection import SelectionModel
    from app.module_registry import ModuleId
    from app.module_execution.executors.positioning import PositioningExecutor
    facts=tuple(replace(f,value=truth) if f.label=='product_truth' else f
        for f in facts_for_module(ModuleId.POSITIONING))
    model=SelectionModel(lambda p,d:p['outputs']['offer'].update(text=sourced(truth)))
    result=asyncio.run(PositioningExecutor(model_call=model,support_selection_wire=True).execute(
        request(ModuleId.POSITIONING,facts=facts,outputs=('offer',))))
    assert result.payload['outputs'][0]['text']==truth and len(model.calls)==1


def test_explicit_source_preserves_numbered_result_without_repair():
    import copy
    from app.module_execution.executors.positioning_support_selection import support_selection_wire_schema,decode_support_selection_wire
    from app.module_execution.executors.schemas import PositioningOutput
    f=fixture(('offer',));f[3][0].value='one session'
    schema=support_selection_wire_schema(f[0],PositioningOutput,*f[2:]);value=output((f[0],schema,*f[2:]))
    value['outputs']['offer']['text']=sourced('one session');before=copy.deepcopy(value)
    decoded=decode_support_selection_wire(value,f[0],PositioningOutput,*f[2:])
    assert value==before and decoded['outputs'][0]['text']=='one session'
