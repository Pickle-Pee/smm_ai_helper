"""Bounded public-copy/demo checks; never a general entailment classifier.

Strategic hypotheses do not prove product outcomes. These checks cover direct
customer-addressed outcome copy and explicit existing-demo assertions in both
intelligence executors, including their structured leaf text.
"""
import re

from app.marketing_orchestrator.quality_gates.contracts import EvidenceSourceClass
from .common import SemanticRule, StatementSemanticsError, factual_competitor_parents

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
These requirements also apply to nested designs, assumptions and limitations.
"""


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
_DEMO_PROPOSALS = frozenset({
    'Check whether a new demo shows the intended comparison.',
    'Проверить, показывает ли новый демонстрационный образец предполагаемое сравнение.',
    'Создать демонстрационный образец, который показывает сравнение снимков.',
    'Create a demo that shows the comparison.',
})
_COUNTERFACTUAL = re.compile(
    r"^(?:Не\s+(?:обещать|использовать\s+обещание)|Do\s+not\s+promise|Avoid\s+promising)\s+"
    r"(?:«[^«»\n]+»|\"[^\"\n]+\"|'[^'\n]+')[.!]?$", re.I)


def selected_sources(statement, local):
    """Only explicit request-local typed witnesses confer product/demo proof."""
    selected = [local[identity] for identity in statement.evidence_ids if identity in local]
    owner = tuple(item.value for item in selected
                  if item.input_key in {"product_truth", "confirmed_business_fact"}
                  and item.record.source_class is EvidenceSourceClass.FIRST_PARTY
                  and isinstance(item.value, str) and item.value.strip())
    demo = tuple(item.value for item in selected if item.input_key == "existing_proof"
                 and item.record.source_class is EvidenceSourceClass.FIRST_PARTY
                 and isinstance(item.value, str) and item.value.strip())
    return owner, demo


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
    if _DEMO.search(text) and _DEMO_FACT.search(text):
        planned = value in _DEMO_PROPOSALS
        if not planned and not _verbatim_leaf(value, demo):
            raise StatementSemanticsError(SemanticRule.DEMONSTRATION_ASSERTION_REQUIRES_SOURCE)


def text_leaves(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from text_leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from text_leaves(item)
