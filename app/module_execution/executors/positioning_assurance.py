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
