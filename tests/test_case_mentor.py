"""Semantic grounding checks against real executor outputs, no external provider."""
from types import SimpleNamespace

import pytest

from app.marketing_copilot.api_errors import CopilotAPIError
from app.marketing_copilot.mentor import explanation, paragraphs
from app.module_registry import ModuleId
from tests.test_strategy_intelligence import run, valid_request, positioning


def case():
    result = run(valid_request(ModuleId.VIRTUAL_CMO))
    packet = valid_request(ModuleId.VIRTUAL_CMO).context_packet
    plan = SimpleNamespace(nodes=[SimpleNamespace(node_id="virtual_cmo", module_id=ModuleId.VIRTUAL_CMO, context_packet=packet)])
    return plan, {"positioning": positioning(), "virtual_cmo": result}


def test_eight_sections_use_saved_business_and_decisions_without_mutating_source():
    plan, accepted = case()
    result = accepted["virtual_cmo"]
    before = repr(result)
    public = explanation("a" * 64, plan, accepted)
    sections = {section.key: section.paragraphs for section in public.sections}
    assert len(sections) == 8
    assert "Grow qualified demand" in sections["goal"]
    assert any("Scheduling software" in value for value in sections["inputs"])
    assert any("Validate the supplied scheduling hypothesis" in value for value in sections["rationale"])
    assert any("Сохранённое основание" in value for value in sections["rationale"])
    assert any("Отдельное экономическое обоснование не сохранено" in value for value in sections["limitations"])
    assert any("Отдельный план эксперимента не сохранён" in value for value in sections["verification"])
    assert any("превосходство" in value for value in sections["alternatives"])
    assert repr(result) == before


def test_no_source_strategy_cannot_be_explained_as_success():
    plan, accepted = case()
    with pytest.raises(CopilotAPIError) as error:
        explanation("a" * 64, plan, {"positioning": accepted["positioning"]})
    assert error.value.status == 409


def test_saved_experiments_keep_expected_signal_separate_from_actual_results():
    plan, accepted = case()
    accepted["experiments"] = run(valid_request(ModuleId.EXPERIMENTS))
    public = explanation("a" * 64, plan, accepted)
    verification = next(section.paragraphs for section in public.sections if section.key == "verification")
    assert "Метрика: Qualified inquiry rate" in verification
    assert any(value.startswith("Ожидаемый сигнал (не фактический результат):") for value in verification)
    assert any(value.startswith("Условие отказа:") for value in verification)


def test_large_paragraphs_preserve_all_text():
    text = "Данные😀" * 2000
    chunks = paragraphs([text])
    assert "".join(chunks) == text
    assert max(map(len, chunks)) <= 4000
