"""Generation guidance and existing guards for the failed course sections."""
import asyncio

import pytest

from app.module_execution.executors import ExecutorOutputError, PositioningExecutor
from app.module_registry import ModuleId
from tests.test_module_executors import fact, request
from tests.test_positioning_support_selection import SelectionModel, qualitative, sourced


TRUTH = (
    "Курс ФотоСтарт длится 6 недель. Участники выполняют практические задания "
    "и получают письменную обратную связь. Для занятий не требуется профессиональное оборудование."
)
FACTS = (
    fact("product", "Курс мобильной фотографии ФотоСтарт"),
    fact("target_or_target_hypothesis", "Начинающие взрослые"),
    fact("product_truth", TRUTH),
)


@pytest.mark.parametrize("name,text", [
    ("demand_context", "Аудитория стремится улучшить навыки, без желания или возможности приобретать профессиональное оборудование."),
    ("value_proposition", "Курс даёт навыки, не требуя профессионального оборудования."),
    ("differentiation", "Курс полностью работоспособен на смартфоне без необходимости профессиональной техники."),
    ("positioning_statement", "Курс помогает улучшить снимки без покупки профессионального оборудования."),
])
def test_observed_equipment_paraphrases_still_fail_before_verification(name, text):
    model = SelectionModel(lambda payload, _: payload["outputs"][name].update(text=qualitative(text)))
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True).execute(
            request(ModuleId.POSITIONING, facts=FACTS, outputs=(name,))))
    assert len(model.calls) == 1


def test_neutral_strategy_and_exact_terms_reach_canonical_without_relaxing_guards():
    names = ("demand_context", "value_proposition", "differentiation", "positioning_statement", "offer", "RTB")
    angle = "Проверить интерес к практике фотографии."

    def select(payload, data):
        for name in names[:4]:
            payload["outputs"][name]["text"] = qualitative(angle)
        truth_key = next(key for key, source in data["positioning_product_sources"].items()
                         if source["category"] == "product_truth")
        payload["outputs"]["offer"]["text"] = sourced(truth_key)

    model = SelectionModel(select)
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True).execute(
        request(ModuleId.POSITIONING, facts=FACTS, outputs=names)))
    rows = {row["output_name"]: row for row in result.payload["outputs"]}
    assert all(rows[name]["text"] == angle for name in names[:4])
    assert rows["offer"]["text"] == rows["RTB"]["text"] == TRUTH
    assert rows["offer"]["evidence_ids"] == rows["RTB"]["evidence_ids"]
    instruction = model.calls[0]["instruction"]
    assert "demand_context describes a need to investigate" in instruction
    assert "not a promise that the course gives" in instruction
    assert "differentiation proposes a comparison to validate" in instruction
    assert "positioning_statement\nrecommends an angle" in instruction
    assert "Keep equipment conditions in the exact SOURCE offer or RTB" in instruction
    assert "HYPOTHESIS and RECOMMENDATION do\nnot authorize new product properties" in instruction
    assert len(model.calls) == 1
