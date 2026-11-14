"""Canonical product assurance detector; generation uses a simple text schema."""
import re


ASSURANCE = re.compile(
    r"\b(?:гаранти\w*|опытн\w*|квалифицированн\w*|сертифицированн\w*|"
    r"профессиональн\w*|безусловн\w*|guarantee\w*|experienced|qualified|"
    r"certified|professional|unconditional\w*)\b", re.IGNORECASE)

# An experiential (learning-by-doing) session is not an experienced instructor.
# Keep this exception adjacent and lexical: no arbitrary intervening words,
# punctuation, staff roles or other assurance families are exempted.
_EXPERIENTIAL_SESSION = re.compile(
    r"\bопытн(?:ое|ого|ому|ым|ом|ые|ых|ыми)\s+"
    r"(?:хобби[-‐‑‒–—])?заняти(?:е|я|ю|ем|и|й|ям|ями|ях)\b", re.IGNORECASE)


_PURCHASE_EQUIPMENT = (
    r"(?:покупать|купить|приобретать|приобрести)\s+профессиональное\s+оборудование"
)
_NO_EQUIPMENT_PURCHASE = (
    rf"(?:(?:без|нет)\s+необходимости|не\s+(?:нужно|требуется))\s+{_PURCHASE_EQUIPMENT}"
    r"|без\s+необходимости\s+(?:покупки|приобретения)"
    r"\s+профессионального\s+оборудования"
)
_EQUIPMENT_NOT_REQUIRED = (
    r"не\s+требуется\s+(?:профессиональное\s+оборудование"
    r"|профессионального\s+оборудования)"
)
NO_EQUIPMENT_PURCHASE = re.compile(rf"\b(?:{_NO_EQUIPMENT_PURCHASE})\b", re.IGNORECASE)
_NO_PROFESSIONAL_EQUIPMENT = re.compile(
    r"\b(?:без\s+профессионального\s+оборудования"
    rf"|{_EQUIPMENT_NOT_REQUIRED}|{_NO_EQUIPMENT_PURCHASE})\b",
    re.IGNORECASE,
)
_EQUIPMENT_TRUTH = re.compile(
    rf"(?:^|[.!\n])\s*(?:для\s+занятий\s+)?"
    rf"(?:{_EQUIPMENT_NOT_REQUIRED}|{_NO_EQUIPMENT_PURCHASE})\s*(?:[.!]|$)",
    re.IGNORECASE,
)

# Detection only for downstream fidelity. Existing POSITIONING assurance/source
# functions below deliberately keep their original matchers and decisions.
_RU_EQUIPMENT = r"(?:профессиональн(?:ое|ого)\s+)?оборудовани[ея]"
_EN_EQUIPMENT = r"(?:professional\s+)?(?:equipment|gear)"
_ADDITIONAL_EQUIPMENT_ABSENCE = (
    r"без\s+оборудования"
    rf"|не\s+(?:нужно|требуется|потребуется)\s+{_RU_EQUIPMENT}"
    rf"|не\s+требует\s+{_RU_EQUIPMENT}"
    rf"|{_RU_EQUIPMENT}\s+не\s+(?:нужно|требуется|потребуется)"
    r"|(?:(?:без|нет)\s+необходимости|не\s+(?:нужно|требуется))\s+"
    r"(?:покупать|купить|приобретать|приобрести)\s+оборудование"
    r"|без\s+необходимости\s+(?:покупки|приобретения)\s+оборудования"
    rf"|without\s+(?:any\s+)?{_EN_EQUIPMENT}"
    rf"|no\s+{_EN_EQUIPMENT}\s+(?:is\s+)?(?:required|needed|necessary)"
    rf"|{_EN_EQUIPMENT}\s+(?:is\s+)?not\s+(?:required|needed|necessary)"
    rf"|requires?\s+no\s+{_EN_EQUIPMENT}"
    rf"|no\s+need\s+to\s+(?:buy|purchase|acquire)\s+(?:any\s+)?{_EN_EQUIPMENT}"
    rf"|(?:do(?:es)?\s+not|don't|doesn't)\s+(?:need|require)\s+(?:any\s+)?{_EN_EQUIPMENT}"
)
_DOWNSTREAM_EQUIPMENT_ABSENCE = re.compile(
    rf"(?:{_NO_PROFESSIONAL_EQUIPMENT.pattern})|\b(?:{_ADDITIONAL_EQUIPMENT_ABSENCE})\b",
    re.IGNORECASE,
)


def equipment_absence_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Recognize finite absence conditions; never prove owner truth/entailment.

    Spans let consumers recognize whole closed research/goal contexts without
    duplicating the equipment vocabulary. No existing POSITIONING caller changes.
    """
    return tuple(match.span() for match in _DOWNSTREAM_EQUIPMENT_ABSENCE.finditer(text))


def supports_no_equipment_purchase(source: str) -> bool:
    """Require an explicit source statement about the absence of the requirement."""
    return bool(_EQUIPMENT_TRUTH.search(source))


def has_product_assurance(text: str) -> bool:
    """Recognize assurances, excluding specific descriptions of the product format."""
    equipment_modifiers = {
        qualification.start()
        for phrase in _NO_PROFESSIONAL_EQUIPMENT.finditer(text)
        for qualification in ASSURANCE.finditer(text, phrase.start(), phrase.end())
    }
    return any(
        match.start() not in equipment_modifiers
        and not _EXPERIENTIAL_SESSION.match(text, match.start())
        for match in ASSURANCE.finditer(text)
    )
