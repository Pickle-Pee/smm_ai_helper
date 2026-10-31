"""Display accepted strategy uncertainty and broad request constraints honestly."""
from copy import deepcopy
from dataclasses import replace

import pytest

from bot import copilot_contracts as dto
from bot import copilot_rendering as render
from app.marketing_copilot.mentor import explanation
from app.module_execution.acceptance import fully_accepted
from app.module_registry import ModuleId
from app.orchestration_runtime.serialization import result_to_json
from app.orchestration_runtime.service import evaluate_result
from tests.test_case_mentor import case
from tests.test_strategy_intelligence import run, valid_request

RID = "a" * 64
STRATEGY_NOTICE = ("Стратегические выводы ниже — рабочие гипотезы и рекомендации; "
                   "спрос, причины отказа и эффективность каналов требуют проверки.")
CONSTRAINTS = (
    "Не выдумывай факты, проценты, суммы, сроки и размеры выборки.",
    "Это отдельный бизнес: не используй сведения прежних проектов или продукт самого Telegram-бота.",
    "Бюджет теста — 5000 ₽.",
    "На проверку есть 14 дней.",
)


def public_experiments():
    return dto.Experiments(designs=[dto.Experiment(hypothesis="Проверить сообщение",
        target_metric="Квалифицированные обращения", intervention="Сравнить сообщения",
        expected_signal="Направление изменения требует проверки", failure_condition="Сигнал не подтверждён",
        minimum_required_inputs=["Исходная частота события"], time_resource_constraints=list(CONSTRAINTS))])


def test_strategy_notice_is_in_first_message_and_preserves_all_nine_sections():
    sections = {key:dto.StrategySection(text=f"Исходная формулировка раздела {key}",
        items=["Сохранённая рекомендация"], numeric_context=["Предоставленная цена — 2500 ₽ за занятие."])
        for key in render.SECTIONS}
    # A causal-looking source formulation remains visible but gets the explicit
    # strategy-wide uncertainty label instead of being rewritten by presentation.
    sections["main_growth_constraint"].text = "Клиенты не оплачивают, потому что ценность неясна."
    result = dto.RunResponse(run_id=RID, status=dto.RunStatus.COMPLETED,
        strategy=dto.Strategy(**sections), experiments=public_experiments())
    before = deepcopy(result.model_dump())
    messages = render.run(result)
    assert messages[0] == "Стратегия готова.\n\n" + STRATEGY_NOTICE
    assert sum(STRATEGY_NOTICE in message for message in messages) == 1
    assert [message.splitlines()[0] for message in messages[1:10]] == list(render.SECTIONS.values())
    for message, section in zip(messages[1:10], sections.values()):
        assert section.text in message
        assert "• " + section.items[0] in message
        assert "• " + section.numeric_context[0] in message
    assert messages[10] == "Эксперименты — отдельный план проверки гипотез"
    assert len(messages) == 12  # No extra notice message or per-section labels.
    assert result.model_dump() == before


@pytest.mark.parametrize("experiments", [None, public_experiments()])
def test_no_strategy_has_no_strategy_notice(experiments):
    result = dto.RunResponse(run_id=RID, status=dto.RunStatus.COMPLETED, experiments=experiments)
    messages = render.run(result)
    assert messages[0] == "Результат готов."
    assert STRATEGY_NOTICE not in "\n".join(messages)


def test_telegram_request_constraints_preserve_generic_and_resource_values():
    result = dto.RunResponse(run_id=RID, status=dto.RunStatus.COMPLETED, experiments=public_experiments())
    before = deepcopy(result.model_dump())
    message = render.run(result)[2]
    assert "Ограничения запроса:\n" in message
    assert "Время и ресурсы:" not in message
    for value in CONSTRAINTS:
        assert "• " + value in message
    assert [message.index(value) for value in CONSTRAINTS] == sorted(message.index(value) for value in CONSTRAINTS)
    assert result.model_dump() == before


def test_mentor_preserves_all_constraints_without_calling_instructions_resources():
    plan, accepted = case()
    request = valid_request(ModuleId.EXPERIMENTS)
    request = replace(request, execution_id="b" * 32, context_packet=replace(request.context_packet, constraints=CONSTRAINTS))
    def include_supplied_constraints(payload, _data):
        for design in payload["experiments"]:
            design["time_resource_constraints"] = list(CONSTRAINTS)
    experiment = run(request, include_supplied_constraints)
    quality = evaluate_result(request.execution_id, experiment, request.upstream_results)
    assert fully_accepted(experiment, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    accepted["experiments"] = experiment
    plan.nodes[0].context_packet = replace(plan.nodes[0].context_packet, constraints=CONSTRAINTS)
    before = {key:result_to_json(value) for key,value in accepted.items()}
    public = explanation(RID, plan, accepted)
    verification = next(section.paragraphs for section in public.sections if section.key == "verification")
    limitations = next(section.paragraphs for section in public.sections if section.key == "limitations")
    for value in CONSTRAINTS:
        assert "Ограничение запроса: " + value in verification
        assert value in limitations
    assert not any("Ресурсное ограничение:" in value for value in verification)
    assert any("Сохранённые ограничения запроса приведены выше." in value for value in limitations)
    assert not any("Сохранённые ресурсные ограничения" in value for value in limitations)
    assert {key:result_to_json(value) for key,value in accepted.items()} == before
