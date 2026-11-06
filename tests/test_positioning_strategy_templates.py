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


def test_output_purposes_cover_exactly_the_positioning_contract():
    from app.module_execution.executors.positioning_strategy import POSITIONING_OUTPUT_PURPOSES

    assert set(POSITIONING_OUTPUT_PURPOSES) == set(ModuleRegistry.load().get(ModuleId.POSITIONING).outputs)
    assert len(POSITIONING_OUTPUT_PURPOSES) == 16


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
    assert choices["target"][0]["required_source_ids"] == ["evd_audience", "evd_identity"]


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


PROFILE_CASES = {
    "photography": choice_evidence(COURSE_TRUTH, "Курс мобильной фотографии ФотоСтарт", "Начинающие взрослые"),
    "ceramics": choice_evidence(CERAMICS_TRUTH, "Мастер-класс по керамике Тёплая глина", "Взрослые без опыта лепки"),
}


@pytest.mark.parametrize("profile", PROFILE_CASES)
def test_profiles_replace_generic_research_filler_with_distinct_grounded_outputs(profile):
    from app.module_execution.executors.positioning_assurance import has_product_assurance

    evidence = PROFILE_CASES[profile]
    choices = build_strategy_choices(evidence)
    strategic_names = set(STRATEGY_OPTIONS) - {"offer", "RTB"}
    assert set(choices) == set(STRATEGY_OPTIONS)
    assert choices["offer"] == choices["RTB"] == ()
    assert len(strategic_names) == 14
    assert all(len(choices[name]) == 1 for name in strategic_names)
    rows = {name: choices[name][0] for name in strategic_names}
    assert len({row["text"] for row in rows.values()}) == 14
    assert all(row["required_source_ids"] == sorted(evidence) for row in rows.values())
    assert all(0 < len(row["text"]) <= 4000 and not has_product_assurance(row["text"])
               and not any(char.isdigit() for char in row["text"]) for row in rows.values())
    assert "освоение новой практики" not in rows["category"]["text"]
    assert "«" + evidence["evd_identity"]["text"] + "»" in rows["positioning_statement"]["text"]
    assert "«" + evidence["evd_audience"]["text"] + "»" in rows["positioning_statement"]["text"]
    assert "ещё" in rows["differentiation"]["text"]
    assert rows["points_of_parity"]["text"].startswith("Гипотеза")
    assert rows["USP_directions"]["text"].count(";") == 2
    assert "Главное сообщение" in rows["message_hierarchy"]["text"]
    assert "Следующий шаг" in rows["message_hierarchy"]["text"]
    assert rows["claim_risks"]["text"].startswith("Рекомендация перед публикацией — проверить, не")
    assert "В беседах проверить" in rows["validation_plan."]["text"]


def test_photography_profile_keeps_roles_useful_without_strengthening_source_terms():
    choices = build_strategy_choices(PROFILE_CASES["photography"])
    rows = {name: options[0]["text"] for name, options in choices.items() if options}
    assert "обучение фотографии" in rows["category"]
    assert "самостоятельным изучением" in rows["frame_of_reference"]
    assert "пробует фотографировать" in rows["demand_context"]
    assert "что пробовать менять в своих фотографиях" in rows["JTBD_frame"]
    assert "письменной обратной связи" in rows["value_proposition"]
    assert "домашними" in rows["claim_risks"] and "персональным" in rows["claim_risks"]
    assert "сверить с владельцем" in rows["validation_plan."]
    assertions = "\n".join(text for name, text in rows.items() if name not in {"claim_risks", "validation_plan."})
    for unsupported in ("домашние задания", "персональная обратная связь", "онлайн", "композиции", "освещения", "быстро", "сертификат"):
        assert unsupported not in assertions


def test_ceramics_profile_preserves_later_collection_and_does_not_invent_technique():
    choices = build_strategy_choices(PROFILE_CASES["ceramics"])
    rows = {name: options[0]["text"] for name, options in choices.items() if options}
    assert "знакомство с керамикой" in rows["category"]
    assert "самостоятельным знакомством" in rows["frame_of_reference"]
    assert "вписать последующее получение" in rows["demand_context"]
    for name in ("value_proposition", "positioning_statement", "USP_directions", "message_hierarchy", "validation_plan."):
        assert "друг" in rows[name]
    assert "не создаёт ли сообщение ожидание выдачи изделия в день занятия" in rows["claim_risks"]
    assert "технику" in rows["claim_risks"] and "уточнить" in rows["claim_risks"] and "у владельца" in rows["claim_risks"]
    rendered = "\n".join(rows.values())
    for unsupported in ("гончарный круг", "ручная пластика", "инструктаж", "расслабление", "не потребуется", "не придётся"):
        assert unsupported not in rendered


@pytest.mark.parametrize("product,truth", [
    ("ФотоСтарт", COURSE_TRUTH),
    ("Бренд Курс фотографии ФотоСтарт", COURSE_TRUTH),
    ("Название с фотографией", COURSE_TRUTH),
    ("Курс кулинарии ФотоСтарт", COURSE_TRUTH),
    ("Мастер-класс керамики Тёплая глина", COURSE_TRUTH),
    ("Курс фотографии ФотоСтарт", CERAMICS_TRUTH),
    ("Тёплая глина", CERAMICS_TRUTH),
    ("Изделия после обжига", CERAMICS_TRUTH),
])
def test_domain_profile_requires_explicit_matching_product_identity_and_complete_truth(product, truth):
    choices = build_strategy_choices(choice_evidence(truth, product))
    assert choices["category"][0]["text"] == "Предлагаем проверить категорию «освоение новой практики»."
    assert all("evd_identity" in row["required_source_ids"] for options in choices.values() for row in options)


@pytest.mark.parametrize("profile", PROFILE_CASES)
@pytest.mark.parametrize("invalid", ["demo", "conditional", "another_truth", "missing_audience"])
def test_profiles_do_not_select_unconfirmed_or_ambiguous_context(profile, invalid):
    from copy import deepcopy

    evidence = deepcopy(PROFILE_CASES[profile])
    if invalid == "demo":
        evidence["evd_truth"]["role"] = "demonstration"
    elif invalid == "conditional":
        evidence["evd_truth"]["text"] = "Возможно, " + evidence["evd_truth"]["text"]
    elif invalid == "another_truth":
        evidence["evd_another_truth"] = {"role": "product_truth", "text": "Условия нужно уточнить."}
    else:
        del evidence["evd_audience"]
    choices = build_strategy_choices(evidence)
    assert choices["category"][0]["text"] == "Предлагаем проверить категорию «освоение новой практики»."


@pytest.mark.parametrize("product,profile", [
    ("Курс фотографии ФотоСтарт", "photography"),
    ("Курс мобильной фотографии ФотоСтарт", "photography"),
    ("Мастер-класс керамики Тёплая глина", "ceramics"),
    ("Мастер-класс по керамике Тёплая глина", "ceramics"),
])
def test_explicit_domain_prefix_variants_enable_the_correct_profile(product, profile):
    truth = COURSE_TRUTH if profile == "photography" else CERAMICS_TRUTH
    choices = build_strategy_choices(choice_evidence(truth, product))
    assert "освоение новой практики" not in choices["category"][0]["text"]


@pytest.mark.parametrize("duration,equipment,expected", [
    (False, True, ("practical_tasks", "written_feedback", "no_equipment")),
    (False, False, ("practical_tasks", "written_feedback")),
    (True, True, ("duration", "practical_tasks", "written_feedback", "no_equipment")),
    (True, False, ("duration", "practical_tasks", "written_feedback")),
])
def test_known_course_source_has_separate_semantic_units(duration, equipment, expected):
    from app.module_execution.executors.positioning_strategy import source_fact_units

    text = ("Курс ФотоСтарт длится 6 недель. " if duration else "")
    text += "Участники выполняют практические задания и получают письменную обратную связь."
    if equipment:
        text += " Для занятий не требуется профессиональное оборудование."
    units = source_fact_units(text)
    assert tuple(row["unit_id"] for row in units) == expected
    slices = {row["unit_id"]: text[row["start_char"]:row["end_char"]] for row in units}
    assert slices["practical_tasks"] == "Участники выполняют практические задания"
    assert slices["written_feedback"] == "и получают письменную обратную связь."
    if duration:
        assert slices["duration"] == "Курс ФотоСтарт длится 6 недель."
    if equipment:
        assert slices["no_equipment"] == "Для занятий не требуется профессиональное оборудование."
    assert all(set(row) == {"unit_id", "label", "start_char", "end_char"}
               and 0 <= row["start_char"] < row["end_char"] <= len(text) for row in units)


def test_ceramics_materials_and_firing_are_distinct_units_with_a_shared_anchor():
    from app.module_execution.executors.positioning_strategy import source_fact_units

    materials, firing, collection = source_fact_units(CERAMICS_TRUTH)
    assert materials["unit_id"] == "materials_included"
    assert firing["unit_id"] == "firing_included"
    assert (materials["start_char"], materials["end_char"]) == (firing["start_char"], firing["end_char"])
    assert materials["label"] != firing["label"]
    assert CERAMICS_TRUTH[materials["start_char"]:materials["end_char"]] == "Материалы и обжиг включены."
    assert collection["unit_id"] == "later_collection"
    assert CERAMICS_TRUTH[collection["start_char"]:collection["end_char"]] == (
        "Участники забирают изделия после обжига в другой день."
    )


@pytest.mark.parametrize("name", ["Фото📷Старт", "Свет cafe\u0301 👩🏽‍🎨", "Участники выполняют практические задания"])
def test_source_units_use_original_unicode_codepoints_even_with_repeated_words_in_title(name):
    from app.module_execution.executors.positioning_strategy import source_fact_units

    prefix = f"Курс {name} длится 6 недель."
    text = prefix + " Участники выполняют практические задания и получают письменную обратную связь."
    duration, practical, feedback = source_fact_units(text)
    assert duration["start_char"] == 0 and duration["end_char"] == len(prefix)
    assert practical["start_char"] == len(prefix) + 1
    assert text[duration["start_char"]:duration["end_char"]] == prefix
    assert text[practical["start_char"]:practical["end_char"]] == "Участники выполняют практические задания"
    assert text[feedback["start_char"]:feedback["end_char"]] == "и получают письменную обратную связь."


@pytest.mark.parametrize("text", [
    "Возможно, " + COURSE_TRUTH,
    "Пример: " + COURSE_TRUTH,
    COURSE_TRUTH + " Дополнительные условия нужно уточнить.",
    COURSE_TRUTH.replace("6 недель", "7 недель"),
    COURSE_TRUTH.replace("письменную", "персональную"),
    COURSE_TRUTH.replace("оборудование.", "оборудование?"),
    "Если участник согласен. " + CERAMICS_TRUTH,
    CERAMICS_TRUTH.replace("в другой день", "в тот же день"),
    "Материалы и обжиг включены.",
    "Получение после обжига.",
    " ",
    None,
])
def test_unknown_or_altered_whole_source_has_no_unit_plan(text):
    from app.module_execution.executors.positioning_strategy import source_fact_units

    assert source_fact_units(text) == ()
