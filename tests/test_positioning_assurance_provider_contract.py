"""Provider generation excludes unsupported qualifications before local guards."""
from jsonschema import Draft202012Validator
import asyncio
import copy
import random
import re
import pytest
from tests.test_positioning_support_selection import fixture, output
from app.module_execution.executors.positioning_assurance import (
    ASSURANCE, STEMS, ALPHABET, qualitative_assurance_pattern,
)
from app.module_execution.executors.numeric_quantity import cardinal_words_for_provider


@pytest.mark.parametrize("text", ["Занятия с опытным мастером.",
    "A guaranteed finished product.", "Professional instruction for beginners."])
def test_unsupported_assurance_is_not_generatable_as_free_text(text):
    f = fixture(("frame_of_reference",))
    payload = output(f)
    payload["outputs"]["frame_of_reference"]["text"] = text
    assert not Draft202012Validator(f[1]).is_valid(payload)


@pytest.mark.parametrize("text", ["Занятия с мастером.", "Попробовать новый опыт.",
    "Новички без опыта.", "An introductory workshop.", "Inexperienced beginners.",
    "Первая строка.\nСледующая строка."])
def test_unqualified_reasoning_and_experience_nouns_remain_generatable(text):
    f = fixture(("frame_of_reference",));payload = output(f)
    payload["outputs"]["frame_of_reference"]["text"] = text
    assert Draft202012Validator(f[1]).is_valid(payload)


@pytest.mark.parametrize("stem", STEMS)
def test_every_finite_assurance_family_is_excluded_case_insensitively(stem):
    rx = re.compile(qualitative_assurance_pattern())
    assert not rx.fullmatch(stem + ".")
    assert not rx.fullmatch(stem.upper() + ".")


def test_positive_word_grammar_matches_reference_without_word_splitting():
    rx = re.compile(qualitative_assurance_pattern())
    rng = random.Random(156)
    alphabet = "".join(STEMS) + "ABC .\n012"
    for _ in range(5000):
        text = "".join(rng.choices(alphabet, k=rng.randint(0,100)))
        words = re.findall(r"[A-Za-zА-Яа-яЁё_]+", text)
        expected = bool(text) and text[-1] not in ALPHABET and not re.search("[0-9]",text)
        expected = bool(expected and not any(any(word.casefold().startswith(stem) for stem in STEMS) for word in words)
            and not any(word.casefold().startswith(prefix)
                for word in words for prefix in cardinal_words_for_provider()))
        assert bool(rx.fullmatch(text)) is expected
    for text in ("опытный.", "опыТНый.", "guaranteed.", "a professional."):
        assert not rx.fullmatch(text)


def test_grammar_has_no_lookarounds_and_is_shared_once_per_wire_schema():
    f = fixture();pattern = qualitative_assurance_pattern()
    assert all(token not in pattern for token in ("(?=", "(?!", "(?<=", "(?<!", "\\1"))
    assert len(pattern.encode()) < 17000
    from app.module_execution.executors.provider_schema import nodes
    assert sum(node.get("pattern") == pattern for node in nodes(f[1])) == 1


def test_word_grammar_does_not_replace_the_canonical_detector():
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
    model = SelectionModel(lambda p,d: p["outputs"]["offer"].update(text=truth))
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
        row=payload["outputs"]["offer"];row["text"]=truth
        if cite_message:
            identity=next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"]=="message")
            alias=next(k for k,v in data["positioning_support_selection_catalog"]["evidence"].items() if v==identity)
            row["evidence_support"][alias]=True
    model=SelectionModel(mutate)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PositioningExecutor(model_call=model,support_selection_wire=True).execute(
            request(ModuleId.POSITIONING,facts=facts,outputs=("offer",))))
    assert len(model.calls)==1


def test_source_without_punctuation_is_not_repaired_by_the_decoder():
    from app.module_execution.executors.positioning_support_selection import support_selection_wire_schema, decode_support_selection_wire
    from app.module_execution.executors.schemas import PositioningOutput
    f=fixture(("offer",));f[3][0].value="An experienced instructor"
    schema=support_selection_wire_schema(f[0],PositioningOutput,*f[2:])
    payload=output((f[0],schema,*f[2:]));payload["outputs"]["offer"]["text"]=f[3][0].value
    before=copy.deepcopy(payload)
    decoded=decode_support_selection_wire(payload,f[0],PositioningOutput,*f[2:])
    assert payload==before and decoded["outputs"][0]["text"]==f[3][0].value
