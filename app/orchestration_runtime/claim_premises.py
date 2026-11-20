"""Bounded lexical guards independent of an auditor's claim labels.

These rules detect known factual-premise failure families, not arbitrary natural
language entailment. A False result is not evidence that a statement is factual
premise free. Callers must retain independent semantic review and fail closed on
uncertainty. Matching never changes the immutable draft or its Unicode offsets.
"""

import re


_FACTUAL_PREMISE = re.compile(
    r"\b(?:"
    # Catch assertion grammar as well as the historical feature vocabulary.
    # Include its whole clause: supporting only an innocuous subject/prefix
    # must not authorize an unsupported predicate farther along the sentence.
    r"(?:course|lessons?|classes?|workshops?|product|service|curriculum|program|participants|learners|students)\s+"
    r"(?:includes?|contains?|offers?|provides?|delivers?|teaches?|covers?|ensures?|receive|receives|gets?|has|have)\s+[^.!?;\n]+"
    r"|(?:курс\w*|урок\w*|заняти\w*|мастер[-\s]класс\w*|продукт\w*|сервис\w*|программ\w*|участник\w*|ученик\w*|студент\w*)\s+"
    r"(?:включа\w*|содерж\w*|предлага\w*|предоставля\w*|обеспечива\w*|обуча\w*|охватыва\w*|получа\w*|име\w*)\s+[^.!?;\n]+"
    # Product delivery format, including a factual premise inside a hypothesis.
    r"|online\s+(?:course|lesson|class|workshop)s?"
    r"|(?:course|lesson|class|workshop)s?\s+(?:(?:is|are|runs?|takes?\s+place)\s+)?online"
    r"|онлайн[-\s]+(?:курс\w*|урок\w*|заняти\w*|обучени\w*)"
    r"|(?:курс\w*|урок\w*|заняти\w*|обучени\w*)\s+(?:(?:проход\w*|провод\w*)\s+)?онлайн"
    # Included activities and service properties.
    r"|homework|домашн\w*\s+задани\w*"
    r"|(?:personal|individual|written)\s+feedback"
    r"|(?:персональн\w*|индивидуальн\w*|письменн\w*)\s+обратн\w*\s+связ\w*"
    r"|pottery\s+wheel|гончарн\w*\s+круг\w*|ручн\w*\s+пластик\w*"
    r"|(?:teacher|instructor|tutor)\s+(?:helps?|support|assistance)"
    r"|(?:help|support|assistance)\s+(?:from|of)\s+(?:a\s+|the\s+)?(?:teacher|instructor|tutor)"
    r"|(?:помощ\w*|поддержк\w*|инструктаж\w*)\s+(?:преподавател\w*|мастер\w*)"
    r"|(?:преподавател\w*|мастер\w*)\s+(?:помога\w*|поддержива\w*|инструктиру\w*)"
    # Specific curriculum topics asserted as part of an existing course.
    r"|(?:course|lessons?|curriculum)\s+(?:covers?|includes?|teaches?)\s+[^.!?;]{0,60}(?:composition|lighting)"
    r"|(?:курс\w*|урок\w*|программ\w*)\s+(?:включа\w*|обуча\w*|охватыва\w*|посвящ\w*)\s+[^.!?;]{0,60}(?:композици\w*|свет\w*)"
    r"|(?:изучени\w*|обучени\w*|упражнени\w*|задани\w*)\s+(?:по\s+)?(?:композици\w*|свет\w*)"
    # Outcomes and comparative superiority remain factual premises under a label.
    r"|guarantee\w*|гаранти\w*"
    r"|(?:course|workshop|class)\s+(?:ensures?|provides?|delivers?)\s+relaxation"
    r"|(?:заняти\w*|мастер[-\s]класс\w*|курс\w*)\s+(?:обеспечива\w*|да[её]т)\s+расслаблени\w*"
    r"|(?:outperforms?|better\s+than)\s+(?:the\s+)?competitors?"
    r"|(?:лучше|эффективнее|превосход\w*)\s+конкурент\w*"
    r")\b",
    re.IGNORECASE,
)

# A complete, narrowly phrased research question can mention a candidate feature
# without asserting that the current product has it. Do not exempt a generic
# 'Hypothesis:'/'Test whether:' prefix: those can contain factual premises.
_PROSPECTIVE_QUESTION = re.compile(
    r"\s*(?:"
    r"(?:test|ask|check|research|validate)\s+(?:whether|if)\s+"
    r"(?:the\s+)?(?:audience|participants|learners|beginners|customers)\s+"
    r"(?:need|want|value|prefer|would\s+value|would\s+prefer)s?\s+"
    r"|(?:проверить|выяснить|исследовать|спросить)[,:]?\s+"
    r"(?:нуж(?:ен|на|но|ны)\s+ли|важ(?:ен|на|но|ны)\s+ли)\s+"
    r"(?:аудитории|участникам|ученикам|новичкам|клиентам)\s+"
    r")"
    # Closed research objects, not arbitrary subordinate product assertions.
    r"(?:an?\s+|the\s+)?(?:online\s+format|homework|personal\s+feedback|written\s+feedback"
    r"|teacher\s+support|онлайн[-\s]формат|домашние\s+задания"
    r"|персональная\s+обратная\s+связь|письменная\s+обратная\s+связь"
    r"|помощь\s+преподавателя)[.?!]?\s*",
    re.IGNORECASE,
)

_NO_FOLLOW_UP = re.compile(
    r"\b(?:"
    r"no\s+(?:further\s+|additional\s+)?(?:action|actions|steps?|follow[-\s]?up)\s+"
    r"(?:(?:is|are|will\s+be)\s+)?(?:needed|required|necessary)"
    r"|(?:no|without)\s+(?:further\s+|additional\s+)?(?:action|actions|follow[-\s]?up)"
    r"|(?:никаких\s+)?(?:дальнейш\w*|дополнительн\w*|последующ\w*)\s+"
    r"действи\w*\s+не\s+(?:потребу\w*|требу\w*|нуж\w*)"
    r"|не\s+(?:потребу\w*|требу\w*|нуж\w*)\s+(?:никаких\s+)?"
    r"(?:дальнейш\w*|дополнительн\w*|последующ\w*)\s+действи\w*"
    r"|без\s+(?:дальнейш\w*|дополнительн\w*|последующ\w*)\s+действи\w*"
    r"|не\s+(?:нужно|прид[её]тся|потребуется)\s+(?:снова\s+)?возвращаться"
    r")\b",
    re.IGNORECASE,
)

_EXPLICIT_LATER_COLLECTION = re.compile(
    # Only a closed neutral inclusion sentence may precede the rule. Arbitrary
    # preceding prose could scope it as a condition, example or proposed change.
    r"\s*(?:(?:материалы\s+и\s+обжиг\s+включены"
    r"|materials\s+and\s+firing\s+are\s+included)[.!]\s+)?(?:"
    r"(?:participants\s+)?collect\s+(?:the\s+)?(?:piece|pieces|item|items)\s+"
    r"(?:another\s+day\s+after\s+firing|after\s+firing[,]?\s+(?:on\s+)?(?:a\s+later|another)\s+day)"
    r"|участники\s+забирают\s+(?:изделия|изделие)\s+после\s+обжига\s+в\s+другой\s+день"
    r")[.!]?\s*",
    re.IGNORECASE,
)


def factual_premise(text: str) -> bool:
    """Detect a known property/outcome family independently of model labels.

    Research questions are exempt only for closed prospective forms. Mixed
    sentences are never exempted by a question elsewhere in the text.
    """
    return bool(factual_premise_ranges(text))


def factual_premise_ranges(text: str) -> tuple[tuple[int, int], ...]:
    """Return known premise ranges in the original Python Unicode string.

    Endpoints are half-open codepoint positions, never UTF-8 byte offsets or
    UTF-16 units. No normalization occurs. Callers should scan the whole draft
    row, rather than its model-selected claim fragments, so dividing a matched
    phrase between fragments cannot suppress the guard.
    """
    if _PROSPECTIVE_QUESTION.fullmatch(text):
        return ()
    return tuple(match.span() for match in _FACTUAL_PREMISE.finditer(text))


def asserts_no_follow_up(text: str) -> bool:
    """Detect the bounded family of known no-further-action promises."""
    return bool(_NO_FOLLOW_UP.search(text))


def source_follow_up(text: str) -> bool | None:
    """Recognize explicit later collection in owner product truth only.

    The caller must establish source identity/role before calling this helper.
    This deliberately does not classify arbitrary source prose, demonstrations,
    conditional pickup or the absence of a rule as 'no follow-up required'.
    """
    return True if _EXPLICIT_LATER_COLLECTION.fullmatch(text) else None
