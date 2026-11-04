"""Positive strategy language contract independent of model-selected labels."""

import pytest

from app.module_registry import ModuleId, ModuleRegistry
from app.module_execution.executors.positioning_strategy import STRATEGY_OPTIONS, build_strategy_choices, safe_strategy_statement


def test_catalogue_covers_each_positioning_output_with_distinct_prospective_options():
    assert set(STRATEGY_OPTIONS) == set(ModuleRegistry.load().get(ModuleId.POSITIONING).outputs)
    all_options = []
    for options in STRATEGY_OPTIONS.values():
        assert len(options) >= 3
        assert len(set(options)) == len(options)
        assert all(safe_strategy_statement(text) for text in options)
        all_options.extend(options)
    assert len(all_options) == len(set(all_options))


@pytest.mark.parametrize("text", [
    "Test whether beginners value knowing what to practice next.",
    "Ask participants whether the timing meets their needs.",
    "Гипотеза: аудитории может быть важна ясность следующего шага.",
    "Проверить интерес к практике фотографии.",
    "Проверить, нужен ли аудитории онлайн-формат.",
    "Ask whether participants want homework.",
    "Test whether beginners value personal feedback.",
    "Проверить, нужна ли аудитории письменная обратная связь.",
    "Выяснить, важна ли участникам персональная обратная связь.",
    "Check if beginners prefer homework.",
])
def test_closed_questions_preserve_useful_hypotheses_and_recommendations(text):
    assert safe_strategy_statement(text)
    assert safe_strategy_statement("\n\t " + text + " \r\n")


@pytest.mark.parametrize("text", [
    "The course is accredited.",
    "The instructor is certified.",
    "Participants leave with finished pieces.",
    "The course includes weekly webinars.",
    "Курс аккредитован.",
    "Участники получают сертификат.",
    "Hypothesis: the course is accredited.",
    "Recommend emphasizing that the course is accredited.",
    "Test whether our online course attracts beginners.",
    "Гипотеза: занятия проходят онлайн.",
    "Ask whether participants want homework supplied by the course.",
    "Проверить, нужен ли аудитории онлайн-формат, который входит в курс.",
    "Проверить интерес к практике фотографии. Курс аккредитован.",
    "Test whether beginners value personal feedback. The instructor is certified.",
    "Test whether beginners value personal feedback, which we provide.",
    "No action is needed after the workshop.",
    "Никаких дальнейших действий не потребуется.",
    "Bounded supported hypothesis: value_proposition",
    "Explore a useful angle.",
    "Проверить\u200b интерес к практике фотографии.",
    "Проверить интерес к практике фотогрaфии.",
    "Проверить интерес к практике фотографии.\x00",
    "",
    "   ",
    None,
])
def test_unknown_or_modified_language_is_not_approved_by_a_hypothesis_label(text):
    assert not safe_strategy_statement(text)


def test_positive_exact_membership_does_not_normalize_internal_unicode_whitespace():
    text = "Проверить интерес к практике фотографии."
    assert safe_strategy_statement(text)
    assert not safe_strategy_statement(text.replace(" ", "\u00a0", 1))


COURSE_TRUTH = (
    "Курс ФотоСтарт длится 6 недель. Участники выполняют практические задания и получают письменную обратную связь. "
    "Для занятий не требуется профессиональное оборудование."
)
CERAMICS_TRUTH = "Материалы и обжиг включены. Участники забирают изделия после обжига в другой день."


def choice_evidence(truth=COURSE_TRUTH, product="Курс ФотоСтарт", audience="Начинающие фотографы"):
    return {
        "evd_identity": {"role": "product_identity", "text": product},
        "evd_audience": {"role": "audience", "text": audience},
        "evd_truth": {"role": "product_truth", "text": truth},
    }


def test_request_scoped_choices_form_a_positioning_proposal_with_exact_identity_and_audience():
    evidence = choice_evidence()
    choices = build_strategy_choices(evidence)
    assert set(choices) == set(STRATEGY_OPTIONS)
    assert choices["offer"] == choices["RTB"] == ()
    proposed, = choices["positioning_statement"]
    assert "«Курс ФотоСтарт»" in proposed["text"]
    assert "«Начинающие фотографы»" in proposed["text"]
    assert "в категории «освоение новой практики»" in proposed["text"]
    assert "письменная обратная связь как ориентир для практики" in proposed["text"]
    assert proposed["required_source_ids"] == ["evd_audience", "evd_identity", "evd_truth"]
    assert choices["target"][0]["required_source_ids"] == ["evd_audience"]


def test_course_and_ceramics_have_distinct_source_bound_value_and_difference_hypotheses():
    course = build_strategy_choices(choice_evidence())
    ceramics = build_strategy_choices(choice_evidence(CERAMICS_TRUTH, "Мастер-класс Тёплая глина", "Взрослые без опыта лепки"))
    for output in ("value_proposition", "differentiation", "points_of_difference", "positioning_statement"):
        assert course[output] != ceramics[output]
        assert all("evd_truth" in row["required_source_ids"] for row in (*course[output], *ceramics[output]))
    assert "прозрачность условий получения изделия" in ceramics["positioning_statement"][0]["text"]
    assert "письменная обратная связь" not in ceramics["positioning_statement"][0]["text"]


@pytest.mark.parametrize("truth", [
    "Возможно, участники выполняют практические задания и получают письменную обратную связь.",
    "Пример: Участники выполняют практические задания и получают письменную обратную связь.",
    "Если владелец подтвердит. Участники выполняют практические задания и получают письменную обратную связь.",
    "Участники выполняют практические задания и получают персональную обратную связь.",
    "Возможно, " + CERAMICS_TRUTH,
    CERAMICS_TRUTH + " Изделие можно забрать сразу.",
    "Условия нужно уточнить.",
])
def test_unknown_conditional_or_modified_truth_does_not_enable_specific_feature_angle(truth):
    choices = build_strategy_choices(choice_evidence(truth))
    assert all("evd_truth" not in row["required_source_ids"] for rows in choices.values() for row in rows)
    assert "ясность выбора и следующего шага" in choices["value_proposition"][0]["text"]


def test_demonstration_cannot_enable_a_product_feature_angle():
    evidence = choice_evidence()
    evidence["evd_truth"]["role"] = "demonstration"
    choices = build_strategy_choices(evidence)
    assert "письменная обратная связь" not in choices["positioning_statement"][0]["text"]


def test_no_raw_source_prose_or_numeric_identity_is_inserted_in_mixed_strategic_text():
    choices = build_strategy_choices(choice_evidence(product="ФотоСтарт 6", audience="Новички от 18 лет"))
    assert all(not any(char.isdigit() for char in row["text"]) for rows in choices.values() for row in rows)
    assert not choices["positioning_statement"]
    assert not choices["target"]
    assert choices["value_proposition"]


def test_ambiguous_identity_slots_do_not_select_an_arbitrary_product():
    evidence = choice_evidence()
    evidence["evd_another_product"] = {"role": "product_identity", "text": "Другой продукт"}
    choices = build_strategy_choices(evidence)
    assert "«Курс ФотоСтарт»" not in choices["positioning_statement"][0]["text"]
    assert "«Другой продукт»" not in choices["positioning_statement"][0]["text"]


def test_choices_are_deterministic_bounded_and_do_not_mutate_source_evidence():
    from copy import deepcopy

    evidence = choice_evidence()
    original = deepcopy(evidence)
    first = build_strategy_choices(evidence)
    assert first == build_strategy_choices(dict(reversed(list(evidence.items()))))
    assert evidence == original
    assert all(len(row["text"]) <= 4000 for rows in first.values() for row in rows)


def test_unknown_sources_cannot_introduce_new_features_via_keyword_matching():
    choices = build_strategy_choices(choice_evidence("Онлайн-курс включает вебинары, сертификат и гарантирует результат."))
    rendered = "\n".join(row["text"] for rows in choices.values() for row in rows)
    assert "вебинар" not in rendered and "сертификат" not in rendered and "гарантирует" not in rendered
