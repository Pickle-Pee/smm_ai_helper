"""Bounded public-copy/demo checks; never a general entailment classifier.

Strategic hypotheses do not prove product outcomes. These checks cover direct
customer-addressed outcome copy and explicit existing-demo assertions in both
intelligence executors, including their structured leaf text.
"""
import re

from .common import EvidenceSourceClass, SemanticRule, StatementSemanticsError, factual_competitor_parents
from .positioning_assurance import equipment_absence_spans

FIDELITY_INSTRUCTION = """
Preserve the epistemic status of upstream positioning. A possible audience goal
or value hypothesis is not a product outcome to promise in public copy. Describe
control/treatment and interventions as operator plans to test message emphasis;
do not invent customer-facing promises such as 'you will learn' or 'получите'.
Direct customer outcome copy requires the COMPLETE verbatim selected local
product_truth/confirmed_business_fact as that text leaf (optional quotation or
simple Copy/Сообщение label). Put test notes in other fields/items. A demonstration,
audience source or strategic HYPOTHESIS is not owner product proof.
If asserting what an existing demonstration shows, quote its COMPLETE exact
existing_proof text as a separate text/item and actually select that evidence ID.
Never paraphrase a sample into proof of course format, recurring service or
effectiveness. Keep interpretation/validation plans in separate items. Creating
a new sample or checking its possible value is a proposal, not existing proof.
Written feedback alone does not establish personal/individual or standardized review, or regular
delivery. A demo comparison does not establish the contents of written feedback.
Do not embed these unconfirmed product attributes inside a HYPOTHESIS. Recognized
format claims need the same complete selected owner source as product copy.
Do not make an unconfirmed richer feedback format a positive understanding,
validation, success or scaling criterion. Check understanding against the complete
owner-confirmed meaning; audience preferences do not prove personal delivery.
Treat upstream risk warnings as constraints, never as extra product capabilities.
Audience preferences/goals and testable value hypotheses may remain open without
asserting new delivery features; confirm proposed product changes with the owner.
These requirements also apply to nested designs, assumptions and limitations.
Preserve equipment qualifiers exactly: no professional equipment required does
not mean no equipment required. If mentioning an equipment-absence condition,
copy the COMPLETE actual selected local product_truth/confirmed_business_fact
as a separate text/item, preserving every sentence and qualifier. Put strategic
interpretation in another leaf without repeating the equipment condition.
Otherwise omit that condition. Closed audience goals, preference/feasibility
research, owner clarification and future validation/publication plans describe
questions or intentions, never established product conditions or public promises.
"""


# Only the equipment span is replaced by this marker. Whole-leaf finite contexts
# may bypass the new equipment check, never any other promise/format/demo guard.
_EQUIPMENT_MARKER = "EQUIPMENT_CONDITION"
_EQUIPMENT_RESEARCH_OR_PLAN = re.compile(
    r"(?:Проверить,\s+предпочитает\s+ли\s+аудитория\s+обучение\s+EQUIPMENT_CONDITION"
    r"|Цель\s+аудитории\s*[—-]\s*заниматься\s+EQUIPMENT_CONDITION"
    r"|(?:Уточнить\s+у\s+владельца,\s+возможно\s+ли|Проверить,\s+возможно\s+ли)\s+"
    r"обучение\s+EQUIPMENT_CONDITION"
    r"|Исследовать\s+интерес\s+аудитории\s+к\s+обучению\s+EQUIPMENT_CONDITION"
    r"|Проверить\s+возможность\s+обучения\s+EQUIPMENT_CONDITION\s+и\s+согласовать\s+"
    r"условия\s+с\s+владельцем\s+до\s+публикации"
    r"|Не\s+обещать\s+(?:обучение|доступность)\s+EQUIPMENT_CONDITION\s+"
    r"без\s+подтверждения\s+владельца"
    r"|Check\s+whether\s+customers\s+prefer\s+learning\s+EQUIPMENT_CONDITION"
    r"|Audience\s+goal:\s*learn\s+EQUIPMENT_CONDITION"
    r"|(?:Confirm\s+with\s+the\s+owner\s+whether|Check\s+whether)\s+learning\s+"
    r"EQUIPMENT_CONDITION\s+is\s+possible"
    r"|Research\s+audience\s+interest\s+in\s+learning\s+EQUIPMENT_CONDITION"
    r"|Test\s+whether\s+learning\s+EQUIPMENT_CONDITION\s+is\s+feasible\s+before\s+"
    r"asking\s+the\s+owner\s+to\s+approve\s+it"
    r"|Do\s+not\s+promise\s+(?:learning|accessibility)\s+EQUIPMENT_CONDITION\s+"
    r"without\s+owner\s+confirmation)[.!?]?", re.I,
)


_OUTCOME = re.compile(
    r"\b(?:получ(?:ите|ишь|и)|науч(?:итесь|ишься|ись)|смож(?:ете|ешь)|"
    r"стан(?:ете|ешь)|осво(?:ите|ишь)|добь(?:ётесь|етесь|ёшься|ешься)|"
    r"you\s+(?:will\s+|can\s+)?(?:get|receive|gain|achieve|learn|master|become)|"
    r"you['’]ll\s+(?:get|receive|gain|achieve|learn|master|become))\b", re.I)
_IMPERATIVE = re.compile(r"(?:^|[«\"':.!?;\n])\s*(?P<verb>learn|master|gain|achieve|receive|become)\b", re.I)
_GOAL_LEAD = re.compile(r"^(?:(?:Customer|Audience|Learning|Desired)\s+goal|Goal):\s*", re.I)
_RESEARCH_LEARNING = re.compile(
    r"^Learn\s+from\s+(?:the\s+)?(?:pilot|survey|interview|test)\w*\s+"
    r"(?:feedback|responses|data|results)(?:\s+(?:about|on|from|for)\s+[^.!?\n]+)?[.!]?$", re.I)
_DIRECT = re.compile(r"\b(?:получ(?:ите|ишь|и)|науч(?:итесь|ишься|ись)|смож(?:ете|ешь)|"
                     r"стан(?:ете|ешь)|осво(?:ите|ишь)|добь(?:ётесь|етесь|ёшься|ешься)|you)\b", re.I)
_PRODUCT_OUTCOME = re.compile(
    r"\b(?:(?:участник\w*|ученик\w*|клиент\w*|слушател\w*)\s+"
    r"(?:получ(?:ит|ат)|науч(?:ится|атся)|осво(?:ит|ят)|сможет|смогут|стан(?:ет|ут))"
    r"|(?:курс|занятие|продукт)\s+(?:даст|позволит|обеспечит|поможет)"
    r"|(?:participants?|customers?|learners?|students?)\s+(?:will|can)\s+"
    r"(?:get|receive|gain|achieve|learn|master|become))\b", re.I)
_COPY_CONTEXT = re.compile(
    r"\b(?:курс\w*|заняти\w*|участник\w*|клиент\w*|слушател\w*|"
    r"сообщени\w*|объявлени\w*|заголов\w*|реклам\w*|"
    r"course|class|participant\w*|customer\w*|message|copy|headline|advert\w*)\b", re.I)
_COPY_LABEL = re.compile(r"\b(?:сообщени\w*|объявлени\w*|заголов\w*|реклам\w*|message|copy|headline|advert\w*)\b", re.I)
_RESEARCH_ACTION = re.compile(
    r"^(?:(?:Проведите|Организуйте|Запустите|Conduct|Run)\b[^.!?\n]*"
    r"\b(?:интервью|опрос\w*|исследован\w*|измерен\w*|interview\w*|survey\w*|research)\b"
    r"|После\s+(?:опроса|интервью|исследования)\b|After\s+(?:the\s+)?(?:survey|interviews?|research)\b)", re.I)
_RESEARCH_RETURN = re.compile(
    r"^(?:получ(?:ите|и)|you\s+(?:will\s+)?(?:get|receive)|you['’]ll\s+(?:get|receive))\s+"
    r"(?:данные|ответы|отклики|наблюдения|обратную\s+связь|data|observations|responses|answers|feedback)"
    r"(?:\s+(?:для|о|об|по|из|от|после|for|about|on|from|after)\s+[^.!?\n]+)?[.!]?$", re.I)
_DEMO = re.compile(r"\b(?:демонстраци\w*|демо(?:[-‐‑–—]?(?:пример|образец|материал|ролик)\w*)?|proof|demonstration\w*|demos?)\b", re.I)
_DEMO_FACT = re.compile(
    r"\b(?:существующ\w*|имеющ\w*|имеется|представлен\w*|показыва\w*|демонстриру\w*|"
    r"подтвержда\w*|доказыва\w*|existing|available|shows?|demonstrates?|proves?|illustrates?)\b", re.I)
_NONASSERTIVE_DEMO_VERBS = (
    re.compile(r"(?:^|;)\s*дополнительно\s+(?P<verb>показывать)\b", re.I),
    re.compile(r"\bесли\s+(?:(?:качественные\s+)?интервью\s+и\s+тест|тест)\s+"
               r"(?P<verb>показывают|показывает)\b", re.I),
)
_RU_TASK_EXAMPLE = r"пример\s+задания"
_RU_FEEDBACK_EXAMPLE = r"пример\s+письменного\s+отклика"
_RU_CREATED_EXAMPLES = (
    rf"(?:{_RU_TASK_EXAMPLE}(?:\s+и\s+{_RU_FEEDBACK_EXAMPLE})?"
    rf"|{_RU_FEEDBACK_EXAMPLE}(?:\s+и\s+{_RU_TASK_EXAMPLE})?)"
)
_EN_TASK_EXAMPLE = r"(?:a\s+(?:task|assignment)\s+example|an\s+example\s+of\s+a\s+(?:task|assignment))"
_EN_FEEDBACK_EXAMPLE = (
    r"(?:a\s+written\s+(?:feedback|response)\s+example|an\s+example\s+of\s+"
    r"(?:written\s+feedback|a\s+written\s+response))"
)
_EN_CREATED_EXAMPLES = (
    rf"(?:{_EN_TASK_EXAMPLE}(?:\s+and\s+{_EN_FEEDBACK_EXAMPLE})?"
    rf"|{_EN_FEEDBACK_EXAMPLE}(?:\s+and\s+{_EN_TASK_EXAMPLE})?)"
)
_PROSPECTIVE_CREATED_DEMO = re.compile(
    r"(?:(?:Подготовить|Создать)\s+(?:новые\s+)?демонстрационные\s+материалы,\s*"
    r"(?:(?P<ru_showing>показывающие)|которые\s+(?P<ru_show>показывают))\s+" + _RU_CREATED_EXAMPLES +
    r"(?:,\s*без\s+предположений\s+о\s+формате\s+доставки)?|"
    r"(?:Prepare|Create)\s+(?:new\s+)?demonstration\s+materials\s+"
    r"(?:(?P<en_showing>showing)|that\s+(?P<en_show>show))\s+" + _EN_CREATED_EXAMPLES +
    r"(?:,\s*without\s+assumptions\s+about\s+(?:the\s+)?delivery\s+format)?)[.!]?", re.I,
)
_DEMO_PROPOSALS = frozenset({
    'Check whether a new demo shows the intended comparison.',
    'Проверить, показывает ли новый демонстрационный образец предполагаемое сравнение.',
    'Создать демонстрационный образец, который показывает сравнение снимков.',
    'Create a demo that shows the comparison.',
})
_COUNTERFACTUAL = re.compile(
    r"^(?:Не\s+(?:обещать|использовать\s+обещание)|Do\s+not\s+promise|Avoid\s+promising)\s+"
    r"(?:«[^«»\n]+»|\"[^\"\n]+\"|'[^'\n]+')[.!]?$", re.I)
_RU_DEMO_SOURCE = r"(?:демонстрационный\s+(?:образец|пример|материал|ролик)|демо)"
_EN_DEMO_SOURCE = r"(?:demo|demonstration)(?:\s+(?:sample|example))?"
_CURRENT_DEMO_SOURCE = re.compile(
    r"(?:" + _RU_DEMO_SOURCE + r"\s+(?:(?:показывает|демонстрирует)\s+"
    r"(?:сравнение снимков|вариант глазурования чаши)|имеется|предоставлен|существует)|"
    r"(?:Имеется|Предоставлен|Существует)\s+" + _RU_DEMO_SOURCE + r"|"
    r"(?:(?:The|A|An)\s+)?(?:(?:existing|provided)\s+)?" + _EN_DEMO_SOURCE +
    r"\s+(?:(?:shows?|demonstrates?)\s+(?:a comparison|the comparison|"
    r"a comparison of photographs|a cup glazing variant|a glazing variant for a cup)|"
    r"exists?|is\s+(?:available|provided))|"
    r"(?:Available|Provided)\s+" + _EN_DEMO_SOURCE + r")\.?", re.I)
_NEGATIVE_DEMO_CLAUSE = (
    r"(?:(?:Существующее|Предоставленное)\s+доказательство\s+ограничено\s+"
    r"демонстрационным\s+образцом\s+и\s+не\s+подтверждает\s+"
    r"(?:масштабную\s+)?эффективность\s+(?:акцента|курса|обучения)|"
    r"Демонстрационный\s+образец\s+не\s+(?:подтверждает|доказывает)\s+"
    r"(?:масштабную\s+)?эффективность\s+(?:акцента|курса|обучения)|"
    r"(?:Existing|Provided)\s+evidence\s+is\s+limited\s+to\s+a\s+demonstration\s+"
    r"sample\s+and\s+does\s+not\s+(?:confirm|prove)\s+(?:the\s+)?"
    r"(?:large-scale\s+)?effectiveness\s+of\s+(?:the\s+)?(?:emphasis|course|training)|"
    r"(?:The\s+)?demonstration\s+sample\s+does\s+not\s+(?:confirm|prove)\s+"
    r"(?:the\s+)?(?:large-scale\s+)?effectiveness\s+of\s+"
    r"(?:the\s+)?(?:emphasis|course|training))"
)
_NEGATIVE_DEMO_LIMITATION = re.compile(
    _NEGATIVE_DEMO_CLAUSE + r"(?:\.\s+" + _NEGATIVE_DEMO_CLAUSE + r")?\.?", re.I)
_NEGATIVE_DEMO_PREFIX = re.compile(_NEGATIVE_DEMO_CLAUSE + r"\b", re.I)
_RU_PERSONAL_FULL = r"личн(?:ый|ая|ое|ые|ого|ой|ому|ым|ом|ую|ых|ыми|ою)"
_RU_DELIVERY_FEEDBACK = (
    r"(?:персональн[а-яё]*|индивидуальн[а-яё]*|" + _RU_PERSONAL_FULL +
    r"|стандартиз(?:ирован|ован)н[а-яё]*)(?:\s*,\s*|\s+(?:и\s+)?)(?:письменн[а-яё]*\s+)?"
    r"(?:обратн[а-яё]*\s+связ[а-яё]*|отклик[а-яё]*|разбор[а-яё]*|отзыв[а-яё]*|рецензи[а-яё]*)"
)
_EN_DELIVERY_FEEDBACK = (
    r"(?:personal(?:ized|ised)?|individual(?:ized|ised)?|standardi[sz]ed)(?:\s*,\s*|\s+(?:and\s+)?)(?:written\s+)?"
    r"(?:feedback|reviews?|responses?|critiques?)"
)
_DELIVERY_FEEDBACK = re.compile(
    r"\b(?:" + _RU_DELIVERY_FEEDBACK + r"|" + _EN_DELIVERY_FEEDBACK + r"|"
    r"(?:письменн[а-яё]*\s+)?(?:обратн[а-яё]*\s+связ[а-яё]*|отклик[а-яё]*)\s+"
    r"(?:(?:является|будет)\s+)?(?:персональн[а-яё]*|индивидуальн[а-яё]*|" + _RU_PERSONAL_FULL +
    r"|лич(?:ен|на|но|ны)|стандартиз(?:ирован|ован)(?:н[а-яё]*|а|о|ы)?)|"
    r"(?:written\s+)?(?:feedback|reviews?)\s+(?:is|are|will\s+be)\s+"
    r"(?:personal(?:ized|ised)?|individual(?:ized|ised)?|standardi[sz]ed))\b", re.I)
_FEEDBACK_CONTENT = re.compile(
    r"\b(?:(?:(?:письменн[а-яё]*\s+)?обратн[а-яё]*\s+связ[а-яё]*|"
    r"письменн[а-яё]*\s+отклик[а-яё]*)\s*(?:,\s*)?"
    r"(?:(?:которая|который|которые)\s+)?(?:(?:может|будет)\s+)?"
    r"(?:показывает|показывать|содержит|содержать|иллюстрирует|иллюстрировать|"
    r"демонстрирует|демонстрировать|включает|включать)\s+"
    r"(?:(?:конкретн[а-яё]*|подробн[а-яё]*|практическ[а-яё]*)\s+){0,2}"
    r"(?:изменени[а-яё]*|сравнени[а-яё]*|разбор[а-яё]*|комментари[а-яё]*|"
    r"содержани[а-яё]*|правк[а-яё]*|рекомендаци[а-яё]*|пример[а-яё]*|ответ[а-яё]*|"
    r"что\s+(?:менять|изменить|улучшить)|как\s+(?:менять|изменить|улучшить))|"
    r"(?:written\s+)?feedback\s+(?:(?:that|which)\s+)?(?:(?:can|may|might|will)\s+)?"
    r"(?:shows?|contains?|illustrates?|demonstrates?|includes?)\s+(?:(?:a|an|the)\s+)?"
    r"(?:(?:specific|concrete|detailed|practical)\s+){0,2}"
    r"(?:changes?|improvements?|comparisons?|reviews?|critiques?|comments?|content|"
    r"examples?|corrections?|recommendations?|answers?|what\s+to\s+(?:change|improve)|"
    r"how\s+to\s+(?:change|improve)))\b", re.I)
_DEMO_FEEDBACK_FORMAT = re.compile(
    r"(?:это\s+иллюстраци[а-яё]*\s+формат[а-яё]*\s+(?:письменной\s+)?обратной\s+связи|"
    r"(?:illustrates?|demonstrates?|shows?)\s+(?:the\s+)?(?:written\s+)?feedback\s+format)", re.I)
_EXISTING_COPY_ASSET = re.compile(
    r"(?:^|;)\s*(?:(?:Использовать|Взять)\s+)?(?:существующ[а-яё]*|текущ[а-яё]*)\s+"
    r"(?:(?:нейтральн[а-яё]*|контрольн[а-яё]*)\s+)?"
    r"(?:сообщени[а-яё]*|текст[а-яё]*|лендинг[а-яё]*|объявлени[а-яё]*|посадочн[а-яё]*\s+страниц[а-яё]*)\b|"
    r"(?:^|;)\s*(?:Use\s+)?(?:the\s+)?(?:existing|current)\s+(?:(?:neutral|control)\s+)?"
    r"(?:message|copy|text|landing(?:\s+page)?|ad(?:vertisement)?|campaign)\b", re.I)
_RU_COPY_ASSET = r"(?:текст|сообщение|лендинг|объявление|посадочная\s+страница)"
_EN_COPY_ASSET = r"(?:text|copy|message|landing(?:\s+page)?|ad)"
_COMPLETED_COPY_APPROVAL = re.compile(
    r"(?:^|;)\s*" + _RU_COPY_ASSET + r"(?:\s+и\s+" + _RU_COPY_ASSET + r")?\s+"
    r"(?:уже\s+)?согласован(?:а|о|ы)?\s+с\s+владельцем\b|"
    r"(?:^|;)\s*(?:the\s+)?" + _EN_COPY_ASSET + r"(?:\s+and\s+(?:the\s+)?" + _EN_COPY_ASSET +
    r")?\s+(?:is|are|has\s+been|have\s+been)\s+(?:already\s+)?approved\s+by\s+(?:the\s+)?owner\b", re.I)
_NEGATIVE_FORMAT_MENTION = re.compile(
    r"(?:^|;)\s*(?:в\s+коммуникации\s+)?избегать\s+формулировок,\s*"
    r"которые\s+можно\s+понять\s+как\s+замену\s+(?P<format>" + _RU_DELIVERY_FEEDBACK +
    r")(?=\s*(?:[;.!?]|$))", re.I)
_NEGATIVE_PROMISE_FORMAT_MENTION = re.compile(
    r"(?:^|;)\s*Не\s+(?:обещать|гарантировать|рекламировать)\s+(?P<format>" + _RU_DELIVERY_FEEDBACK +
    r")(?:(?:\s+без\s+подтверждения\s+владельца)|,\s*пока\s+формат\s+обратной\s+связи"
    r"(?:\s+и\s+объ[её]м)?\s+не\s+согласован(?:ы)?\s+с\s+владельцем)?(?=\s*(?:[;.!?]|$))", re.I)
_EN_NEGATIVE_PROMISE_FORMAT_MENTION = re.compile(
    r"(?:^|;)\s*Do\s+not\s+(?:promise|guarantee|advertise)\s+(?P<format>" + _EN_DELIVERY_FEEDBACK +
    r")(?:\s+without\s+owner\s+confirmation)?(?=\s*(?:[;.!?]|$))", re.I)
_FORMAT_RESEARCH_OR_GOAL = re.compile(
    r"(?:(?:(?:Исследовать|Проверить|Выяснить|Спросить),\s*)?"
    r"(?:важна|нужна|полезна)\s+ли\s+(?:аудитории|участникам)\s+" + _RU_DELIVERY_FEEDBACK + r"|"
    r"(?:Исследовать|Проверить|Выяснить|Спросить),\s*(?:предпочитает|хочет|ценит)\s+ли\s+"
    r"аудитория\s+" + _RU_DELIVERY_FEEDBACK + r"|"
    r"(?:Цель|Потребность|Желание)\s+аудитории\s*[:—-]\s*(?:получить|получать|найти)\s+"
    + _RU_DELIVERY_FEEDBACK + r"|"
    r"Гипотеза(?:\s+предпочтения\s+аудитории)?:\s*(?:аудитории\s+(?:важна|нужна|полезна)|"
    r"аудитория\s+(?:предпочитает|ценит|хочет))\s+" + _RU_DELIVERY_FEEDBACK + r"|"
    r"(?:Research|Check|Ask|Explore|Test)\s+(?:whether|if)\s+(?:the\s+)?"
    r"(?:audience|customers|participants)\s+(?:want|value|prefer|need)\s+" + _EN_DELIVERY_FEEDBACK + r"|"
    r"(?:Do|Would)\s+(?:the\s+)?(?:audience|customers|participants)\s+"
    r"(?:want|value|prefer|need)\s+" + _EN_DELIVERY_FEEDBACK + r"|"
    r"(?:Customer|Audience|Learning|Desired)\s+goal:\s*(?:receive|get|find|obtain)\s+"
    + _EN_DELIVERY_FEEDBACK + r"|"
    r"(?:Audience\s+preference\s+hypothesis|Hypothesis):\s*(?:the\s+)?"
    r"(?:audience|customers|participants)\s+(?:want|value|prefer|need)\s+"
    + _EN_DELIVERY_FEEDBACK + r"|"
    r"(?:Собрать|Получить)\s+" + _RU_DELIVERY_FEEDBACK +
    r"\s+(?:представителей\s+)?аудитории\s+о\s+(?:тестовом\s+)?сообщении|"
    r"(?:Collect|Gather)\s+" + _EN_DELIVERY_FEEDBACK +
    r"\s+from\s+(?:the\s+)?audience\s+about\s+(?:the\s+)?(?:test\s+)?message|"
    r"Уточнить\s+у\s+владельца,\s*включает\s+ли\s+курс\s+" + _RU_DELIVERY_FEEDBACK + r"|"
    r"Confirm\s+with\s+the\s+owner\s+whether\s+the\s+course\s+includes\s+" + _EN_DELIVERY_FEEDBACK + r")[.?]?", re.I)
_FORMAT_POLICY_WARNINGS = frozenset({
    'Рекомендация перед публикацией — проверить, не подменяет ли сообщение практические задания домашними, а письменную обратную связь персональным разбором; уточнить темы курса и темп освоения у владельца.',
    'Не приравнивать письменную обратную связь к персональному разбору без подтверждения владельца.',
    'Do not equate written feedback with personalized review without owner confirmation.',
})
_CONTENT_RESEARCH_OR_GOAL = re.compile(
    r"(?:(?:Исследовать|Проверить|Выяснить),\s*нужна\s+ли\s+аудитории\s+"
    r"письменная\s+обратная\s+связь,\s+которая\s+показывает\s+конкретные\s+изменения\s+в\s+снимках|"
    r"Цель\s+аудитории\s*[:—-]\s*получить\s+письменную\s+обратную\s+связь,\s+которая\s+"
    r"показывает\s+конкретные\s+изменения\s+в\s+снимках|"
    r"(?:Research|Check|Ask)\s+whether\s+customers\s+want\s+written\s+feedback\s+that\s+"
    r"shows\s+concrete\s+changes\s+in\s+photos|"
    r"Audience\s+goal:\s*receive\s+written\s+feedback\s+that\s+shows\s+concrete\s+changes\s+in\s+photos)[.?]?", re.I)


def typed_literal_sources(evidence_ids, local):
    """Only explicit request-local typed witnesses confer product/demo proof."""
    selected = [local[identity] for identity in evidence_ids if identity in local]
    owner = tuple(item.value for item in selected
                  if item.input_key in {"product_truth", "confirmed_business_fact"}
                  and item.record.source_class is EvidenceSourceClass.FIRST_PARTY
                  and isinstance(item.value, str) and item.value.strip())
    demo = tuple(item.value for item in selected if item.input_key == "existing_proof"
                 and item.record.source_class is EvidenceSourceClass.FIRST_PARTY
                 and isinstance(item.value, str) and item.value.strip())
    return owner, demo


def selected_sources(statement, local):
    return typed_literal_sources(statement.evidence_ids, local)


def comparison_quotes(request, statement):
    """An exact attributed competitor fact stays foreign, never product proof."""
    allowed = factual_competitor_parents(request)
    return tuple(allowed[identity].value for identity in statement.parent_claim_ids
                 if identity in allowed and allowed[identity].value.startswith(
                     ("The competitor site states: ", "На сайте конкурента указано: ")))


def _verbatim_leaf(text, sources):
    for source in sources:
        if text in (source, '«' + source + '»', '"' + source + '"',
                    'Сообщение: «' + source + '»', 'Copy: "' + source + '"'):
            return True
    return False


def validate_leaf(text, *, owner=(), demo=(), comparisons=(), copy_field=False):
    """Reject bounded material claims before canonical persistence, per leaf.

    No producer kind, global source availability or appended quotation authorizes
    a new promise. Research results are not course fulfillment. A closed whole
    counterfactual warning and an exact attributed competitor quote remain safe.
    Other prose is NOT proven safe by the absence of these lexical signals.
    """
    value = text.strip()
    if value in comparisons or _COUNTERFACTUAL.fullmatch(value):
        return
    if (copy_field and (_EXISTING_COPY_ASSET.search(value) or _COMPLETED_COPY_APPROVAL.search(value))
            and not _verbatim_leaf(value, owner)):
        raise StatementSemanticsError(SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH)
    equipment = equipment_absence_spans(value)
    if equipment:
        equipment_question = False
        if len(equipment) == 1 and not copy_field and not any(mark in value for mark in ('«', '»', '"', "'")):
            start, end = equipment[0]
            context = value[:start] + _EQUIPMENT_MARKER + value[end:]
            equipment_question = bool(_EQUIPMENT_RESEARCH_OR_PLAN.fullmatch(context))
        if not (equipment_question or _verbatim_leaf(value, owner)):
            raise StatementSemanticsError(SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH)
    negative_formats = {match.span('format') for pattern in (
        _NEGATIVE_FORMAT_MENTION, _NEGATIVE_PROMISE_FORMAT_MENTION, _EN_NEGATIVE_PROMISE_FORMAT_MENTION)
        for match in pattern.finditer(value)}
    delivery_formats = tuple(match for match in _DELIVERY_FEEDBACK.finditer(value)
                             if match.span() not in negative_formats)
    if (delivery_formats or _FEEDBACK_CONTENT.search(value)
            or (_DEMO.search(value) and _DEMO_FEEDBACK_FORMAT.search(value))):
        format_question = (_FORMAT_RESEARCH_OR_GOAL.fullmatch(value)
                           or _CONTENT_RESEARCH_OR_GOAL.fullmatch(value))
        if not (format_question or value in _FORMAT_POLICY_WARNINGS or _verbatim_leaf(value, owner)):
            raise StatementSemanticsError(SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH)
    outcomes = tuple(_OUTCOME.finditer(text))
    quoted = any(mark in text for mark in ('«', '»', '"')) or bool(re.search(r"(?<!\w)'[^\n]+'(?!\w)", text))
    research = (len(outcomes) == 1 and _RESEARCH_ACTION.search(value)
                and _RESEARCH_RETURN.fullmatch(text[outcomes[0].start():].strip())
                and not _COPY_LABEL.search(text) and not quoted)
    goal = _GOAL_LEAD.match(value)
    imperatives = [match for match in _IMPERATIVE.finditer(value)
                   if not (goal and match.start('verb') == goal.end())]
    if _RESEARCH_LEARNING.fullmatch(value):
        imperatives = []
    imperative_copy = bool(imperatives) and (
        copy_field or quoted or _COPY_CONTEXT.search(value) or any(match.start('verb') == 0 for match in imperatives))
    product_copy = _PRODUCT_OUTCOME.search(text) and (copy_field or quoted or _COPY_LABEL.search(text))
    if product_copy or imperative_copy or (outcomes and not research and (_DIRECT.search(text) or _COPY_CONTEXT.search(text) or quoted)):
        if not _verbatim_leaf(value, owner):
            raise StatementSemanticsError(SemanticRule.CUSTOMER_PROMISE_REQUIRES_OWNER_SOURCE)
    # These bounded operator/conditional-research forms do not assert what an
    # existing demonstration proves. Exclude only their verb token, never the
    # rest of the leaf: another positive/relative assertion still blocks.
    nonassertive = set() if copy_field or quoted else {
        match.span("verb") for pattern in _NONASSERTIVE_DEMO_VERBS for match in pattern.finditer(text)}
    if not copy_field and not quoted:
        created = _PROSPECTIVE_CREATED_DEMO.fullmatch(value)
        if created:
            offset = len(text) - len(text.lstrip())
            for group in ("ru_showing", "ru_show", "en_showing", "en_show"):
                if created.group(group) is not None:
                    start, end = created.span(group)
                    nonassertive.add((offset + start, offset + end))
    demo_facts = tuple(match for match in _DEMO_FACT.finditer(text) if match.span() not in nonassertive)
    if _DEMO.search(text) and demo_facts:
        planned = value in _DEMO_PROPOSALS
        if not planned and not _verbatim_leaf(value, demo):
            raise StatementSemanticsError(SemanticRule.DEMONSTRATION_ASSERTION_REQUIRES_SOURCE)


def validate_limitation(text, local):
    """Permit closed negative coverage only in global output limitations.

    A request-local first-party current demo can witness its lack of established
    effectiveness, never a positive product outcome or a new demo-format fact.
    The entire leaf must contain only one or two closed negative clauses. No
    appended assertion, parent hypothesis or generic proof role grants authority.
    The complete source must match a closed presence/comparison/glazing shape;
    there is no arbitrary object or suffix. Other valid source paraphrases can
    reject. This is deliberately not general NLP existence inference.
    """
    value = text.strip()
    if _NEGATIVE_DEMO_LIMITATION.fullmatch(value):
        if any(item.input_key == "existing_proof"
               and item.record.source_class is EvidenceSourceClass.FIRST_PARTY
               and isinstance(item.value, str) and _CURRENT_DEMO_SOURCE.fullmatch(item.value.strip())
               for item in local.values()):
            return
        raise StatementSemanticsError(SemanticRule.DEMONSTRATION_ASSERTION_REQUIRES_SOURCE)
    if _NEGATIVE_DEMO_PREFIX.match(value):
        # A recognized negative clause cannot launder appended positive prose,
        # even where the old lexical co-occurrence check would miss its verb.
        raise StatementSemanticsError(SemanticRule.DEMONSTRATION_ASSERTION_REQUIRES_SOURCE)
    validate_leaf(text)


def text_leaves(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from text_leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from text_leaves(item)
