"""Experiential session wording does not claim an instructor's qualification."""
from types import SimpleNamespace

import pytest

from app.module_execution.executors.positioning import PositioningExecutor
from app.module_execution.executors.common import StatementSemanticsError, SemanticRule
from app.module_execution.executors.schemas import OutputStatement


def statement(text, name="frame_of_reference"):
    return OutputStatement(output_name=name, text=text, kind="HYPOTHESIS",
        confidence="MEDIUM", evidence_ids=["product"], parent_claim_ids=[])


def sources():
    return {"product": SimpleNamespace(input_key="product_truth", value=
        "Проводим занятия с мастером; материалы и обжиг включены.")}


@pytest.mark.parametrize("text", [
    "Оффлайн-опытное хобби-занятие для взрослых, где человек делает изделие под руководством мастера.",
    "Гипотеза: соответствует ожиданиям категории опытных занятий — место для практики с инструктором и доступом к материалам, аналогично другим студиям и мастер-классам.",
    "Попробовать опытное занятие с мастером.",
    "Формат опытного занятия.", "Гипотеза об опытном хобби‑занятии.",
])
def test_practice_session_does_not_require_a_staff_qualification_quote(text):
    value = statement(text)
    before = value.model_dump()
    PositioningExecutor(model_call=None).validate_statement(value, sources(), {})
    assert value.model_dump() == before


@pytest.mark.parametrize("text", [
    "Занятие с опытным мастером.", "Сопровождение опытных педагогов.",
    "Опытное сопровождение на занятии.",
    "Опытное занятие с профессиональным инструктором.",
    "Опытных занятий достаточно для гарантированного результата.",
    "Опытная команда проводит хобби-занятия.",
])
def test_staff_expertise_and_other_assurances_still_require_actual_proof(text):
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement(text), sources(), {})
    assert caught.value.rule is SemanticRule.PRODUCT_ASSURANCE_SUPPORT_REQUIRED


def test_equipment_requirement_is_not_a_product_assurance():
    value = statement(
        "Курс для людей, которые хотят снимать лучше без профессионального оборудования, "
        "опора на практические задания и обратную связь."
    )
    source = {"product": SimpleNamespace(input_key="product_truth", value=
        "Курс для начинающих, снимающих на телефон или первую камеру. "
        "Включает практические задания и письменную обратную связь преподавателя.")}
    PositioningExecutor(model_call=None).validate_statement(value, source, {})


@pytest.mark.parametrize("text", [
    "Курс без профессионального оборудования ведёт профессиональный преподаватель.",
    "Курс включает профессиональное оборудование.",
    "Курс без профессионального оборудования гарантирует результат.",
])
def test_equipment_reference_preserves_affirmative_assurance_checks(text):
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement(text), sources(), {})
    assert caught.value.rule is SemanticRule.PRODUCT_ASSURANCE_SUPPORT_REQUIRED
