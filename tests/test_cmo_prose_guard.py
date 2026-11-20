"""Wire v15/v17: free CMO prose cannot be a schema key or a bare kind label."""
import hashlib
import re

from jsonschema import Draft202012Validator
import pytest

from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.cmo_demo_plans import DEMO_FREE_PATTERN, LABEL_STEMS
from app.module_execution.executors.cmo_source_bets import BET_RELATIONS
from app.module_execution.executors.cmo_source_diagnoses import DIAGNOSIS_RELATIONS
from app.module_execution.executors.cmo_support_wire import WIRE_VERSION, support_selection_catalog
from app.module_execution.executors.qualitative_generation import QUALITATIVE_GENERATION_PATTERN
from tests.test_cmo_support_wire import contracts, decode, scoped_request, wire_output


# Observed in the Telegram bakery run on c6c5dc5 (marker KHLEBQOLHTGDR): a bet item and summaries.
OBSERVED_LEAKS = ("audience_understanding_ru", "RECOMMENDATION", "HYPOTHESIS")


@pytest.mark.parametrize("text", [
    *OBSERVED_LEAKS,
    *BET_RELATIONS, *DIAGNOSIS_RELATIONS,
    " RECOMMENDATION. ", "HYPOTHESIS:", "Hypothesis", "recommendation", "primary_evidence_key",
    "Проверить audience_value_ru в беседах.",
    # The label stems are closed as whole word families: a label cannot open a sentence either.
    "Recommendation: keep complete owner terms.", "Test the hypothesis that pickup terms are clear.",
])
def test_schema_keys_and_kind_labels_are_not_free_prose(text):
    assert re.fullmatch(DEMO_FREE_PATTERN, text) is None


@pytest.mark.parametrize("text", [
    "Провести короткие беседы с жителями района о предзаказе.",
    "Сфокусировать ресурсы на понятном процессе самовывоза",
    "Test the assumption that pickup terms are clear.",
    "Предлагаемый акцент — онлайн-запись и ясные условия.",
    "Рекомендуем сохранить полные условия владельца; гипотезу проверить в беседах.",
    "Ретаргетинг",
])
def test_ordinary_prose_remains_available(text):
    assert re.fullmatch(DEMO_FREE_PATTERN, text)


def test_shared_qualitative_pattern_used_by_other_modules_is_unchanged():
    assert hashlib.sha256(QUALITATIVE_GENERATION_PATTERN.encode()).hexdigest().startswith("8cfe49af")
    assert re.fullmatch(QUALITATIVE_GENERATION_PATTERN, "audience_understanding_ru")
    assert WIRE_VERSION == "virtual_cmo.support_selection.v17"


def test_free_prose_pattern_is_the_one_the_provider_accepted():
    # The provider returns an empty "incomplete" response (zero tokens) for patterns it cannot
    # compile; offline tests cannot see that. The v15/v16 pattern with a two-word structure
    # W(?:SEP+W)+ failed that way on 15.11.2026, this exact pattern was accepted
    # (req_c028d93eb3f54dbaaa1ee2529e34f39d). Re-probe the provider before changing the pin.
    assert LABEL_STEMS == ("recomm", "hypoth")
    assert hashlib.sha256(DEMO_FREE_PATTERN.encode()).hexdigest().startswith("3b0da3a77c2edf06")
    assert ")+" not in DEMO_FREE_PATTERN and "(?!" not in DEMO_FREE_PATTERN and "(?=" not in DEMO_FREE_PATTERN
    assert DEMO_FREE_PATTERN.count("^") - DEMO_FREE_PATTERN.count("[^") == 1 and DEMO_FREE_PATTERN.count("$") == 1


@pytest.mark.parametrize("field,value", [
    ("text", "RECOMMENDATION"),
    ("text", "HYPOTHESIS"),
    ("items", ["audience_understanding_ru"]),
    ("items", ["Провести беседы", "message_preference_ru"]),
])
def test_leaked_key_or_label_fails_the_wire_schema_and_the_decoder(field, value):
    req = scoped_request(outputs=("strategic_priorities", "resource_priorities"))
    canonical, schema, ids, parents, catalog = contracts(req)
    payload = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    assert Draft202012Validator(schema).is_valid(payload)
    payload["outputs"]["strategic_priorities"][field] = value
    assert not Draft202012Validator(schema).is_valid(payload)
    with pytest.raises(ModuleExecutionContractError):
        decode(req, payload)
