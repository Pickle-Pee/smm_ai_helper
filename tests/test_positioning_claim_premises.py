"""Known factual-premise escapes must not depend on a model-selected label."""

import pytest

from app.orchestration_runtime.claim_premises import (
    asserts_no_follow_up,
    factual_premise,
    factual_premise_ranges,
    source_follow_up,
)


@pytest.mark.parametrize("text", [
    "The lessons are online.",
    "Hypothesis: our online course may appeal to beginners.",
    "Test whether our online lessons appeal to beginners.",
    "Learners do homework and receive personal feedback.",
    "The sample uses a pottery wheel.",
    "Recommend promoting assistance from the instructor.",
    "The course covers composition and lighting.",
    "The course includes weekly webinars.",
    "The service offers a certificate.",
    "Participants receive a workbook.",
    "The workshop provides relaxation.",
    "Hypothesis: guaranteed results will appeal to beginners.",
    "The course outperforms competitors.",
    "Гипотеза: онлайн-курс привлечёт новичков.",
    "Курс проходит онлайн.",
    "Рекомендуем подчеркнуть домашние задания и персональную обратную связь.",
    "Участникам доступна помощь преподавателя.",
    "Мастер помогает участникам за гончарным кругом.",
    "Программа включает изучение композиции и света.",
    "Курс включает еженедельные вебинары.",
    "Участники получают сертификат.",
    "В программу входят упражнения по композиции.",
    "Занятие обеспечивает расслабление.",
    "Гипотеза: гарантия результата привлечёт аудиторию.",
    "Курс эффективнее конкурентов.",
    "🧑🏽‍🎓 Гипотеза: онлайн-уроки с домашними заданиями интересны аудитории.",
    "Проверить, нужен ли аудитории онлайн-формат. Курс включает домашние задания.",
])
def test_known_product_premise_survives_hypothesis_or_recommendation_label(text):
    assert factual_premise(text)


@pytest.mark.parametrize("text", [
    "Test whether beginners value knowing what to practice next.",
    "Ask participants whether the timing meets their needs.",
    "Гипотеза: аудитории может быть важна ясность следующего шага.",
    "Проверить, нужен ли аудитории онлайн-формат.",
    "Выяснить, важна ли участникам персональная обратная связь.",
    "Test whether participants want personal feedback.",
    "Check if beginners prefer homework.",
    "Проверить, нужны ли новичкам домашние задания.",
    "Исследовать интерес к пробному занятию.",
    "Предложить протестировать сообщение о понятном следующем шаге.",
])
def test_useful_strategic_hypotheses_and_prospective_questions_are_not_facts(text):
    assert not factual_premise(text)


@pytest.mark.parametrize("text", [
    "No action is needed after the workshop.",
    "No further actions will be required.",
    "Hypothesis: no further action is necessary.",
    "Никаких дальнейших действий не потребуется.",
    "После занятия не потребуется никаких дополнительных действий.",
    "Готовое изделие без последующих действий.",
    "Не придётся снова возвращаться.",
])
def test_no_follow_up_detection_is_independent_of_auditor_flag(text):
    assert asserts_no_follow_up(text)


@pytest.mark.parametrize("source", [
    "Collect the piece another day after firing.",
    "Collect the piece after firing, on a later day.",
    "Participants collect the pieces after firing another day.",
    "Материалы и обжиг включены. Участники забирают изделия после обжига в другой день.",
    "Участники забирают изделия после обжига в другой день.",
])
def test_explicit_owner_later_collection_has_a_bounded_structured_meaning(source):
    assert source_follow_up(source) is True


@pytest.mark.parametrize("source", [
    "Materials are included.",
    "No follow-up is required.",
    "If firing is selected, collect the piece another day after firing.",
    "The example says: Collect the piece another day after firing.",
    "Example. Collect the piece another day after firing.",
    "If firing is selected. Collect the piece another day after firing.",
    "Do not collect the piece another day after firing.",
    "Возможно, участники забирают изделия после обжига в другой день.",
    "Участники не забирают изделия после обжига в другой день.",
    "В примере: участники забирают изделия после обжига в другой день.",
    "Забрать можно позднее.",
])
def test_ambiguous_or_absent_fulfillment_rules_are_unknown_not_false(source):
    assert source_follow_up(source) is None


def test_whole_row_ranges_detect_property_split_between_claims():
    fragments = ("Hypothesis: personal ", "feedback would appeal to beginners.")
    assert all(not factual_premise(fragment) for fragment in fragments)
    text = "".join(fragments)
    ((start, end),) = factual_premise_ranges(text)
    assert text[start:end] == "personal feedback"
    assert start < len(fragments[0]) < end


def test_ranges_refer_to_unchanged_unicode_codepoints():
    prefix = "🧑🏽‍🎓 cafe\u0301: "
    text = prefix + "personal feedback"
    assert factual_premise_ranges(text) == ((len(prefix), len(text)),)
    start, end = factual_premise_ranges(text)[0]
    assert text[start:end] == "personal feedback"
    assert start != len(prefix.encode("utf-8"))


def test_assertion_range_includes_the_predicate_object_not_only_product_subject():
    text = "The course includes weekly webinars."
    ((start, end),) = factual_premise_ranges(text)
    assert text[start:end] == "course includes weekly webinars"


def test_prospective_question_has_no_premise_ranges():
    assert factual_premise_ranges("Проверить, нужен ли аудитории онлайн-формат.") == ()
