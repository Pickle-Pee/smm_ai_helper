"""Free provider text must not respell unsupported quantities as words."""
import pytest
import asyncio
import re
from jsonschema import Draft202012Validator
from tests.test_positioning_support_selection import fixture, output


@pytest.mark.parametrize("text", ["Материалы и обжиг в одном занятии.",
    "A course lasting six weeks.", "A single introductory session."])
def test_free_text_cannot_generate_word_quantities(text):
    f=fixture(("points_of_difference",));value=output(f)
    value["outputs"]["points_of_difference"]["text"]=text
    assert not Draft202012Validator(f[1]).is_valid(value)


def test_complete_shared_cardinal_lexicon_is_excluded_as_whole_words():
    from app.module_execution.executors.numeric_quantity import cardinal_words_for_provider, has_numeric_quantity
    from app.module_execution.executors.positioning_assurance import qualitative_assurance_pattern, ALPHABET
    words=cardinal_words_for_provider();rx=re.compile(qualitative_assurance_pattern())
    assert isinstance(words,frozenset) and {"одном","one","six","single","двумя"} <= words
    assert all(word and word==word.casefold() and set(word)<=ALPHABET for word in words)
    for word in words:
        assert not rx.fullmatch(word+'.') and not rx.fullmatch(word.upper()+'.')
    # Canonical validation keeps its unit-aware semantics. The provider branch is
    # deliberately conservative even when a cardinal is only an article.
    assert not has_numeric_quantity("one should learn")
    assert has_numeric_quantity("one short session")


@pytest.mark.parametrize("text", ["Однако вывод требует проверки.", "Триггер записи стоит проверить.",
    "Статья о процессе занятия.", "Предложить вводное занятие.", "Consider oneself a beginner.",
    "Acquire skills once comfortable.", "Attract first customers."])
def test_longer_noncardinal_words_and_ordinals_are_not_blocked(text):
    from app.module_execution.executors.positioning_assurance import qualitative_assurance_pattern
    assert re.fullmatch(qualitative_assurance_pattern(),text)


@pytest.mark.parametrize("truth", ["Курс длится шесть недель.", "Курс длится 6 недель."])
def test_actual_supplied_word_or_digit_quantity_remains_an_exact_literal_choice(truth):
    from dataclasses import replace
    from tests.test_module_executors import facts_for_module,request
    from tests.test_positioning_support_selection import SelectionModel
    from app.module_registry import ModuleId
    from app.module_execution.executors.positioning import PositioningExecutor
    facts=tuple(replace(f,value=truth) if f.label=='product_truth' else f
        for f in facts_for_module(ModuleId.POSITIONING))
    model=SelectionModel(lambda p,d:p['outputs']['offer'].update(text=truth))
    result=asyncio.run(PositioningExecutor(model_call=model,support_selection_wire=True).execute(
        request(ModuleId.POSITIONING,facts=facts,outputs=('offer',))))
    assert result.payload['outputs'][0]['text']==truth and len(model.calls)==1


def test_cardinal_grammar_does_not_serialize_a_qualified_or_numbered_result_differently():
    import copy
    from app.module_execution.executors.positioning_support_selection import support_selection_wire_schema,decode_support_selection_wire
    from app.module_execution.executors.schemas import PositioningOutput
    f=fixture(('offer',));f[3][0].value='one session'
    schema=support_selection_wire_schema(f[0],PositioningOutput,*f[2:]);value=output((f[0],schema,*f[2:]))
    value['outputs']['offer']['text']='one session';before=copy.deepcopy(value)
    decoded=decode_support_selection_wire(value,f[0],PositioningOutput,*f[2:])
    assert value==before and decoded['outputs'][0]['text']=='one session'
