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
    "Test which task the audience wants to complete when choosing.",
    "Ask the audience whether the stated conditions meet their needs.",
    "Гипотеза: аудитории может быть важна ясность следующего шага.",
    "Проверить, какие ситуации заставляют аудиторию искать альтернативу текущему выбору.",
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
    "Проверить, какие ситуации заставляют аудиторию искать альтернативу текущему выбору. Курс аккредитован.",
    "Test whether beginners value personal feedback. The instructor is certified.",
    "Test whether beginners value personal feedback, which we provide.",
    "No action is needed after the workshop.",
    "Никаких дальнейших действий не потребуется.",
    "Bounded supported hypothesis: value_proposition",
    "Explore a useful angle.",
    "Проверить,\u200b какие ситуации заставляют аудиторию искать альтернативу текущему выбору.",
    "Проверить, какие ситуации заставляют аудиторию искать альтернативу текущему выбoру.",
    "Проверить, какие ситуации заставляют аудиторию искать альтернативу текущему выбору.\x00",
    "",
    "   ",
    None,
])
def test_unknown_or_modified_language_is_not_approved_by_a_hypothesis_label(text):
    assert not safe_strategy_statement(text)


def test_positive_exact_membership_does_not_normalize_internal_unicode_whitespace():
    text = "Проверить, какие ситуации заставляют аудиторию искать альтернативу текущему выбору."
    assert safe_strategy_statement(text)
    assert not safe_strategy_statement(text.replace(" ", "\u00a0", 1))


COURSE_TRUTH = (
    "Курс ФотоСтарт длится 6 недель. Участники выполняют практические задания и получают письменную обратную связь. "
    "Для занятий не требуется профессиональное оборудование."
)
CERAMICS_TRUTH = "Материалы и обжиг включены. Участники забирают изделия после обжига в другой день."

# Real Telegram-shaped slots: lower-case starts, genitive product phrases,
# trailing periods and owner conditions joined by ";".
DOMAINS = {
    "course": ("Курс мобильной фотографии ФотоСтарт", "Начинающие взрослые", COURSE_TRUTH),
    "ceramics": ("Мастер-класс по керамике Тёплая глина", "Взрослые без опыта лепки", CERAMICS_TRUTH),
    "bakery": ("пекарни «Хлебный двор», которая продаёт хлеб по предзаказу.",
               "жители района, которые покупают свежий хлеб к выходным.",
               "заказ принимается накануне вечером; хлеб забирают самовывозом из пекарни в субботу утром, доставки нет."),
    "b2b": ("сервиса бухгалтерского сопровождения «Баланс» для небольших компаний.",
            "владельцы небольших компаний без штатного бухгалтера.",
            "договор заключается минимум на квартал; первичные документы клиент передаёт сам; налоговые споры не ведём."),
    "dentist": ("стоматологической клиники «Улыбка» у метро.",
                "взрослые, которые откладывают визит к стоматологу.",
                "приём только по записи; стоимость лечения определяется после осмотра."),
}
NON_EDUCATION = ("bakery", "b2b", "dentist")
EDUCATION_VOCABULARY = ("курс", "обучен", "практик", "навык", "участник", "заняти", "урок", "знакомств",
                        "ученик", "студент", "мастер-класс", "learn", "practi", "beginner", "participant",
                        "course", "lesson", "skill")


def choice_evidence(truth=COURSE_TRUTH, product="Курс ФотоСтарт", audience="Начинающие фотографы"):
    return {
        "evd_identity": {"role": "product_identity", "text": product},
        "evd_audience": {"role": "audience", "text": audience},
        "evd_truth": {"role": "product_truth", "text": truth},
    }


def domain_choices(domain):
    product, audience, truth = DOMAINS[domain]
    return build_strategy_choices(choice_evidence(truth, product, audience))


def template_shape(domain):
    """Rendered choices with the quoted owner slots replaced by placeholders."""
    from app.module_execution.executors.positioning_strategy import _quoted

    product, audience, _ = DOMAINS[domain]
    return {name: [(row["text"].replace(_quoted(product), "«PRODUCT»").replace(_quoted(audience), "«AUDIENCE»"),
                    row["required_source_ids"]) for row in rows]
            for name, rows in domain_choices(domain).items()}


def test_request_scoped_choices_form_a_positioning_proposal_with_exact_identity_and_audience():
    evidence = choice_evidence()
    choices = build_strategy_choices(evidence)
    assert set(choices) == set(STRATEGY_OPTIONS)
    assert choices["offer"] == choices["RTB"] == ()
    proposed, = choices["positioning_statement"]
    assert "«Курс ФотоСтарт»" in proposed["text"]
    assert "«Начинающие фотографы»" in proposed["text"]
    assert "полное изложение условий владельца без сокращений" in proposed["text"]
    assert proposed["required_source_ids"] == ["evd_audience", "evd_identity", "evd_truth"]
    assert choices["target"][0]["required_source_ids"] == ["evd_audience", "evd_identity"]


def test_every_strategic_output_has_a_choice_for_telegram_shaped_slots():
    for domain in DOMAINS:
        choices = domain_choices(domain)
        assert all(choices[name] for name in set(STRATEGY_OPTIONS) - {"offer", "RTB"}), domain


def test_templates_do_not_depend_on_the_product_domain():
    shapes = [template_shape(domain) for domain in DOMAINS]
    assert all(shape == shapes[0] for shape in shapes)


def test_non_education_products_receive_no_education_vocabulary():
    from app.module_execution.executors.positioning_strategy import _quoted

    for domain in NON_EDUCATION:
        product, audience, _ = DOMAINS[domain]
        for name, rows in domain_choices(domain).items():
            for row in rows:
                text = row["text"].replace(_quoted(product), "").replace(_quoted(audience), "").lower()
                assert not [word for word in EDUCATION_VOCABULARY if word in text], (domain, name, row["text"])
    static = "\n".join(text for options in STRATEGY_OPTIONS.values() for text in options).lower()
    assert not [word for word in EDUCATION_VOCABULARY if word in static]


def test_owner_terms_are_referenced_as_a_whole_never_fragmented_or_restated():
    for domain, (_, _, truth) in DOMAINS.items():
        rendered = "\n".join(row["text"] for rows in domain_choices(domain).values() for row in rows)
        clauses = [clause.strip(" .") for part in truth.split(";") for clause in part.split(". ")]
        assert not [clause for clause in clauses if len(clause) > 12 and clause in rendered], domain


def test_trailing_sentence_period_of_a_quoted_slot_is_not_doubled_inside_quotes():
    statement, = domain_choices("bakery")["positioning_statement"]
    assert "«жители района, которые покупают свежий хлеб к выходным»" in statement["text"]
    assert ".»" not in statement["text"]


def test_owner_terms_bind_value_and_difference_hypotheses_only_when_supplied():
    with_terms = build_strategy_choices(choice_evidence())
    evidence = choice_evidence()
    del evidence["evd_truth"]
    without_terms = build_strategy_choices(evidence)
    for output in ("value_proposition", "differentiation", "points_of_difference", "positioning_statement"):
        assert all("evd_truth" in row["required_source_ids"] for row in with_terms[output])
        assert all("evd_truth" not in row["required_source_ids"] for row in without_terms[output])
    assert "ясность выбора и следующего шага" in without_terms["value_proposition"][0]["text"]


def test_demonstration_cannot_bind_owner_terms():
    evidence = choice_evidence()
    evidence["evd_truth"]["role"] = "demonstration"
    choices = build_strategy_choices(evidence)
    assert all("evd_truth" not in row["required_source_ids"] for rows in choices.values() for row in rows)


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
    rendered = "\n".join(row["text"] for rows in choices.values() for row in rows)
    assert "«Курс ФотоСтарт»" not in rendered
    assert "«Другой продукт»" not in rendered


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


def test_choices_assert_no_product_assurance_or_known_factual_premise():
    from app.module_execution.executors.positioning_assurance import has_product_assurance
    from app.orchestration_runtime.claim_premises import factual_premise

    for domain in DOMAINS:
        for rows in domain_choices(domain).values():
            for row in rows:
                assert not has_product_assurance(row["text"]), row["text"]
                assert not factual_premise(row["text"]), row["text"]


def test_acceptance_texts_have_no_special_strategy_or_source_decomposition():
    import app.module_execution.executors.positioning_strategy as strategy

    assert not hasattr(strategy, "source_fact_units")
    assert template_shape("course") == template_shape("ceramics") == template_shape("bakery")
