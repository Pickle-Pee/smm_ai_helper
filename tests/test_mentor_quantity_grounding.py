"""Free Mentor dialogue must not invent a test population or numeric advice."""
import asyncio
import json

import pytest

from app.marketing_copilot.api_errors import ProviderUnavailable
from app.marketing_copilot.mentor import CaseMentorService
from app.marketing_copilot.mentor_contracts import MentorQuestion
from app.marketing_copilot.mentor_contracts import MentorGeneration
from app.marketing_copilot.mentor_grounding import MentorGroundingError, validate_answer_quantities


def packet():
    return {"accepted_case": [{"key": "inputs", "text": "Продукт: занятия с мастером; материалы и обжиг включены; выдача после обжига."}],
            "current_question": "Что мы продвигаем и какой следующий шаг? Не добавляй исходные данные.",
            "dialogue": [], "feedback": []}


def generation(text, *, unknowns=()):
    return json.dumps({"focus": "overview", "paragraphs": [text],
                       "source_sections": ["inputs"], "unknowns": list(unknowns)}, ensure_ascii=False)


@pytest.mark.parametrize("text", [
    "Запланируйте небольшой пул сессий (например, 4–8 участников) как тестовую партию.",
    "Для проверки достаточно двух занятий.",
    "Предлагаю бюджет 5000 рублей — это лишь гипотетическое распределение.",
])
def test_invented_mentor_quantity_is_rejected_before_answer_persistence(text):
    async def check():
        service = CaseMentorService(None, None)
        finished = []
        async def claim(*args):
            return packet()
        async def model(**kwargs):
            return generation(text)
        async def finish(*args):
            finished.append(args[-1])
        service._claim_question = claim
        service._finish_question = finish
        service.model_call = model
        with pytest.raises(ProviderUnavailable):
            await service.question(123, "a" * 64, MentorQuestion(request_key="quantity", question="Что дальше?"))
        assert finished == [None]
    asyncio.run(check())


@pytest.mark.parametrize("text", ["4–8 участников", "двух занятий", "6weeks", "sample4to8", "participants8", "SAMPLE_SIZE_8"])
def test_earlier_ai_prose_and_generated_strategy_cannot_authorize_quantities(text):
    data = packet()
    data["accepted_case"].append({"key": "rationale", "text": text})
    data["dialogue"] = [{"user": "Уточни план", "assistant": text}]
    with pytest.raises(MentorGroundingError, match="numerical_support_required"):
        validate_answer_quantities(MentorGeneration.model_validate_json(generation(text)), data)


@pytest.mark.parametrize("location", ["input", "question", "prior_user", "feedback", "metrics"])
def test_literal_source_excerpt_is_allowed_without_altering_generated_answer(location):
    data = packet()
    source = "Подтверждаю: длительность курса — 6 недель; обратная связь письменная."
    if location == "input":
        data["accepted_case"][0]["text"] = source
    elif location == "question":
        data["current_question"] = source
    elif location == "prior_user":
        data["dialogue"] = [{"user": source, "assistant": "Иное предложение"}]
    else:
        data["feedback"] = [{"notes": source if location == "feedback" else "Отчёт",
                            "metrics": source if location == "metrics" else "", "analysis": {}}]
    generated = MentorGeneration.model_validate_json(generation("длительность курса — 6 недель"))
    before = generated.model_dump_json()
    validate_answer_quantities(generated, data)
    assert generated.model_dump_json() == before
    with pytest.raises(MentorGroundingError):
        validate_answer_quantities(MentorGeneration.model_validate_json(generation("Прогресс гарантирован за 6 недель")), data)


def test_deterministic_report_arithmetic_is_available_but_not_new_model_arithmetic():
    data = packet()
    data["feedback"] = [{"notes": "Отчёт", "metrics": "", "analysis": {"calculations": {"cost_per_lead": "500 RUB"}}}]
    validate_answer_quantities(MentorGeneration.model_validate_json(generation("500 RUB")), data)
    with pytest.raises(MentorGroundingError):
        validate_answer_quantities(MentorGeneration.model_validate_json(generation("250 RUB")), data)


@pytest.mark.parametrize("text", ["1) Проверьте спрос качественно.", "2. Уточните вместимость.", "• Выдача после обжига."])
def test_structural_list_indices_are_not_test_quantities(text):
    validate_answer_quantities(MentorGeneration.model_validate_json(generation(text)), packet())


@pytest.mark.parametrize("text", ["1) Наберите 4–8 участников.", "2. Проведите два занятия.", "4–8 участников", "1.5% конверсии"])
def test_list_prefix_does_not_hide_quantitative_content(text):
    with pytest.raises(MentorGroundingError):
        validate_answer_quantities(MentorGeneration.model_validate_json(generation(text)), packet())


def test_only_exact_copied_identifier_is_metadata_and_unknowns_are_checked():
    data = packet()
    data["dialogue"] = [{"user": "Сегмент AUDIENCE_PRIOR_ONLY_481", "assistant": "Данные отсутствуют"}]
    validate_answer_quantities(MentorGeneration.model_validate_json(generation("Для сегмента AUDIENCE_PRIOR_ONLY_481 проверьте отклик.")), data)
    with pytest.raises(MentorGroundingError):
        validate_answer_quantities(MentorGeneration.model_validate_json(generation("Для сегмента AUDIENCE_PRIOR_ONLY_482 проверьте отклик.")), data)
    with pytest.raises(MentorGroundingError):
        validate_answer_quantities(MentorGeneration.model_validate_json(generation("Уточните вместимость.", unknowns=["Нужно ли 8 участников?"])), data)


@pytest.mark.parametrize("prefix", ["• ", "- ", "* ", "1) ", "2. ", "• 1) "])
def test_bulleted_source_quotes_keep_authority_but_do_not_hide_new_quantities(prefix):
    data = packet()
    data["current_question"] = "Доступный бюджет 50 000 RUB"
    emitted = MentorGeneration.model_validate_json(generation(prefix + "50 000 RUB"))
    before = emitted.model_dump_json()
    validate_answer_quantities(emitted, data)
    assert emitted.model_dump_json() == before
    with pytest.raises(MentorGroundingError):
        validate_answer_quantities(MentorGeneration.model_validate_json(generation(prefix + "4–8 участников")), data)
