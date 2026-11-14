"""CMO wire v13: demo materials only as SOURCE facts or closed new-demo plans.

Regression for Telegram graph f4bec03b (6df396a) and live course 1df91294 (fcbac48):
free-text paraphrases of prospective demo plans kept failing the downstream demo
check. The provider schema now forbids demo vocabulary in free CMO prose and offers
closed, domain-independent plan sentences that pass unchanged downstream checks.
"""
import asyncio
import json
import re

from jsonschema import Draft202012Validator
import pytest

from app.module_execution.acceptance import fully_accepted
from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.cmo_demo_plans import (
    DEMO_FREE_PATTERN, DEMO_PLAN_NOTES, DEMO_STEMS, DEMO_WORDS,
)
from app.module_execution.executors.cmo_support_wire import (
    RISKS_DEFINITION, STATEMENTS, TRADEOFFS_DEFINITION, WIRE_VERSION, support_selection_catalog,
)
from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage
from app.module_execution.executors.downstream_fidelity import validate_leaf
from app.module_execution.executors.numeric_quantity import has_numeric_quantity
from app.module_execution.executors.qualitative_generation import QUALITATIVE_GENERATION_PATTERN
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.orchestration_runtime.serialization import result_from_json, result_to_json
from app.orchestration_runtime.service import evaluate_result
from tests.test_cmo_generation_policy import DEMO_SOURCE, source_contracts, source_request
from tests.test_cmo_support_wire import contracts, decode, scoped_request, wire_output

OBSERVED_FREE_DEMO_LEAVES = (
    # Telegram f4bec03b on 6df396a, resource_priorities.items[1]
    "Сделать демонстрационный материал, показывающий сравнение снимков без дополнительных обещаний.",
    # Live course 1df91294 on fcbac48
    "Сфокусировать ресурсы на качественных беседах с целевой аудиторией и на создании демонстраций, "
    "показывающих полную последовательность задания и отклика.",
    "Параллельно подготовить демонстрационный фрагмент, показывающий полную цепочку: задание — выполненный "
    "снимок — письменный отклик, и использовать его в тестовой коммуникации.",
    "Положительная валидированная реакция на демонстрационный фрагмент, показывающий последовательность "
    "задания и отклика.",
)
OTHER_FORBIDDEN = (
    "Подготовить демо-материал для беседы.", "ДЕМОНСТРАЦИЯ ценности", "Показать демо аудитории",
    "Use the demo in interviews", "Prepare demonstrations of the offer", "Collect proof from customers",
    "Demonstrate the value", "Сравнить два варианта сообщения",
)
ALLOWED_PROSE = (
    "Проверить у аудитории ценность письменной обратной связи до масштабирования.",
    "Уточнить демографические признаки аудитории в беседах.",
    "Сохранить демократичный тон сообщения.",
    "Обсудить предоставленный образец с владельцем.",
    "Clarify demographic segments before scaling.",
)
PLAN_OUTPUTS = ("strategic_priorities", "resource_priorities", "roadmap", "decision_triggers.")


@pytest.mark.parametrize("text", OBSERVED_FREE_DEMO_LEAVES + OTHER_FORBIDDEN)
def test_free_prose_pattern_rejects_demo_vocabulary_and_counts(text):
    assert re.fullmatch(DEMO_FREE_PATTERN, text) is None


@pytest.mark.parametrize("text", ALLOWED_PROSE)
def test_free_prose_pattern_keeps_ordinary_qualitative_prose(text):
    assert re.fullmatch(DEMO_FREE_PATTERN, text)
    assert re.fullmatch(QUALITATIVE_GENERATION_PATTERN, text)


def test_demo_free_pattern_is_a_strict_restriction_of_the_shared_pattern():
    for text in (*OBSERVED_FREE_DEMO_LEAVES, *OTHER_FORBIDDEN[:-1], *ALLOWED_PROSE):
        if re.fullmatch(DEMO_FREE_PATTERN, text):
            assert re.fullmatch(QUALITATIVE_GENERATION_PATTERN, text)
    assert {"демо", "demo", "proof"} <= DEMO_WORDS and DEMO_STEMS == ("демонс", "demonst")


@pytest.mark.parametrize("note", DEMO_PLAN_NOTES)
def test_closed_plans_are_bounded_digit_free_and_pass_unchanged_leaf_checks(note):
    assert 1 <= len(note) <= 300 and not has_numeric_quantity(note)
    assert re.fullmatch(QUALITATIVE_GENERATION_PATTERN, note)
    assert re.fullmatch(DEMO_FREE_PATTERN, note) is None  # only reachable through the closed enum
    validate_leaf(note)
    validate_leaf(note, owner=("Участники выполняют практические задания.",))
    validate_leaf(note, demo=(DEMO_SOURCE,))


def test_schema_offers_plans_only_on_other_strategy_items():
    _, schema, ids, parents, _ = contracts(scoped_request())
    defs = schema["$defs"]
    other = defs[STATEMENTS[1]]["properties"]["items"]["items"]["anyOf"]
    assert other[-1]["enum"] == list(DEMO_PLAN_NOTES)
    main = defs[STATEMENTS[0]]["properties"]["items"]["items"]
    assert "anyOf" not in main and main["pattern"] == DEMO_FREE_PATTERN
    for name in (RISKS_DEFINITION, TRADEOFFS_DEFINITION):
        assert "anyOf" not in defs[name]["properties"]["items"]["items"]
        assert not set(defs[name]["properties"]["items"]["items"]["enum"]) & set(DEMO_PLAN_NOTES)
    for definition in (STATEMENTS[0], STATEMENTS[1], TRADEOFFS_DEFINITION):
        assert defs[definition]["properties"]["text"]["pattern"] == DEMO_FREE_PATTERN
    assert schema["properties"]["wire_contract_version"]["enum"] == [WIRE_VERSION]
    assert WIRE_VERSION == "virtual_cmo.support_selection.v13"


@pytest.mark.parametrize("name", PLAN_OUTPUTS)
@pytest.mark.parametrize("note", DEMO_PLAN_NOTES)
def test_closed_plan_passes_normal_executor_and_quality(name, note):
    req = scoped_request()
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        payload = wire_output(req.expected_outputs, data["support_selection_catalog"], data.get("cmo_source_selection_catalog"))
        payload["outputs"][name]["items"] = ["Interview prospective customers", note]
        assert Draft202012Validator(kwargs["response_schema"]).is_valid(payload)
        return json.dumps(payload)
    result = asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert len(result.normalized_result.claims) == 9
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    assert result_from_json(result_to_json(result)) == result
    assert any(note in claim.value for claim in result.normalized_result.claims)


@pytest.mark.parametrize("leaf", OBSERVED_FREE_DEMO_LEAVES)
@pytest.mark.parametrize("name,field", [("resource_priorities", "items"), ("roadmap", "items"),
                                        ("decision_triggers.", "items"), ("main_growth_constraint", "items"),
                                        ("strategic_priorities", "text"), ("trade_offs", "text")])
def test_observed_free_demo_leaves_are_rejected_by_decoder(leaf, name, field):
    req = scoped_request()
    _, _, ids, parents, _ = contracts(req)
    payload = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    if field == "items":
        payload["outputs"][name]["items"] = [leaf]
    else:
        payload["outputs"][name]["text"] = leaf
    with pytest.raises(ModuleExecutionContractError):
        decode(req, payload)


def test_executor_rejects_free_demo_plan_at_schema_stage():
    req = scoped_request()
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        payload = wire_output(req.expected_outputs, data["support_selection_catalog"])
        payload["outputs"]["resource_priorities"]["items"] = [OBSERVED_FREE_DEMO_LEAVES[0]]
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model, support_selection_wire=True).execute(req))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_demo_source_token_and_closed_plan_coexist_on_one_output():
    req = source_request()
    _, schema, ids, parents, _, choices = source_contracts(req)
    marker = next(iter(choices))
    payload = wire_output(req.expected_outputs, support_selection_catalog(ids, parents), choices)
    payload["outputs"]["resource_priorities"]["items"] = [marker, DEMO_PLAN_NOTES[1]]
    assert Draft202012Validator(schema).is_valid(payload)
    decoded = decode(req, payload)
    row = next(o for o in decoded["outputs"] if o["output_name"] == "resource_priorities")
    assert row["items"] == [DEMO_SOURCE, DEMO_PLAN_NOTES[1]]


def test_previous_wire_version_payload_is_rejected():
    req = scoped_request()
    _, _, ids, parents, _ = contracts(req)
    payload = wire_output(req.expected_outputs, support_selection_catalog(ids, parents))
    payload["wire_contract_version"] = "virtual_cmo.support_selection.v12"
    with pytest.raises(ModuleExecutionContractError):
        decode(req, payload)
