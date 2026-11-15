"""Wire v16: equipment conditions are owner terms, never free CMO prose."""
import re

from jsonschema import Draft202012Validator
import pytest

from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.cmo_demo_plans import (
    DEMO_FREE_PATTERN, EQUIPMENT_PLAN_NOTES, EQUIPMENT_STEMS, EQUIPMENT_WORDS, PLAN_NOTES,
)
from app.module_execution.executors.cmo_support_wire import support_selection_catalog
from app.module_execution.executors.downstream_fidelity import validate_leaf
from app.module_execution.executors.positioning_assurance import equipment_absence_spans
from tests.test_cmo_generation_policy import source_contracts, source_request
from tests.test_cmo_support_wire import contracts, decode, owner_terms_for, scoped_request, wire_output


# Fragments and paraphrases of an owner condition; the Telegram course leaf was
# ";"-joined and carried a duration, so it had no SOURCE token (graph 012fa4b7).
FREE_EQUIPMENT_LEAVES = (
    "профессиональное оборудование не нужно",
    "Подчеркнуть обучение без профессионального оборудования.",
    "Не требуя профессионального оборудования, предложение доступно новичкам.",
    "Аудитории важно заниматься без покупки оборудования.",
    "Проверить, какое оборудование есть у аудитории.",
    "No professional equipment is required for the classes.",
    "Emphasize learning without any gear.",
)
OWNER_EQUIPMENT = ("Участники выполняют практические задания и получают письменную обратную связь. "
                   "Для занятий не требуется профессиональное оборудование.")


def test_equipment_vocabulary_covers_the_downstream_absence_detector():
    assert EQUIPMENT_STEMS == ("оборудован", "equipment") and EQUIPMENT_WORDS == {"gear"}
    for leaf in FREE_EQUIPMENT_LEAVES:
        assert re.fullmatch(DEMO_FREE_PATTERN, leaf) is None, leaf
    for phrase in ("без оборудования обучение проще", "оборудование не требуется вовсе",
                   "without equipment it is easier", "no gear is needed here"):
        assert equipment_absence_spans(phrase) and re.fullmatch(DEMO_FREE_PATTERN, phrase) is None


@pytest.mark.parametrize("text", [
    "Провести беседы с аудиторией о формате занятий.",
    "Geared messaging remains ordinary prose.",
    "Сверить сообщение с полным описанием владельца.",
])
def test_ordinary_prose_without_equipment_words_remains_available(text):
    assert re.fullmatch(DEMO_FREE_PATTERN, text)


@pytest.mark.parametrize("note", EQUIPMENT_PLAN_NOTES)
def test_closed_equipment_plans_assert_no_requirement_and_pass_downstream_unchanged(note):
    assert note in PLAN_NOTES and len(note) <= 300
    assert not equipment_absence_spans(note)
    assert not any(char.isdigit() for char in note)
    assert re.fullmatch(DEMO_FREE_PATTERN, note) is None  # only reachable through the closed enum
    validate_leaf(note)
    validate_leaf(note, owner=(OWNER_EQUIPMENT,))


@pytest.mark.parametrize("leaf", FREE_EQUIPMENT_LEAVES)
@pytest.mark.parametrize("name,field", [("resource_priorities", "items"), ("roadmap", "items"),
                                        ("main_growth_constraint", "items"),
                                        ("strategic_priorities", "text"), ("trade_offs", "text")])
def test_free_equipment_prose_fails_the_wire_schema_and_the_decoder(leaf, name, field):
    req = scoped_request()
    canonical, schema, ids, parents, catalog = contracts(req)
    payload = wire_output(req.expected_outputs, support_selection_catalog(ids, parents),
                          owner_terms=owner_terms_for(req))
    assert Draft202012Validator(schema).is_valid(payload)
    payload["outputs"][name][field] = leaf if field == "text" else [leaf]
    assert not Draft202012Validator(schema).is_valid(payload)
    with pytest.raises(ModuleExecutionContractError):
        decode(req, payload)


def test_complete_qualitative_owner_condition_still_renders_whole_through_source():
    req = source_request("confirmed_business_fact", OWNER_EQUIPMENT, names=("strategic_priorities",))
    _, schema, ids, parents, _, choices = source_contracts(req)
    marker = next(key for key, row in choices.items() if row["text"] == OWNER_EQUIPMENT)
    payload = wire_output(req.expected_outputs, support_selection_catalog(ids, parents), choices,
                          owner_terms=owner_terms_for(req))
    payload["outputs"]["strategic_priorities"]["items"] = [marker, EQUIPMENT_PLAN_NOTES[0]]
    assert Draft202012Validator(schema).is_valid(payload)
    row = decode(req, payload)["outputs"][0]
    assert row["items"] == [OWNER_EQUIPMENT, EQUIPMENT_PLAN_NOTES[0]]
    assert choices[marker]["evidence_id"] in row["evidence_ids"]
