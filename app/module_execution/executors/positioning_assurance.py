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


_NO_PROFESSIONAL_EQUIPMENT = re.compile(
    r"\bбез\s+(?P<qualification>профессионального)\s+оборудования\b", re.IGNORECASE
)


def has_product_assurance(text: str) -> bool:
    """Recognize assurances, excluding specific descriptions of the product format."""
    equipment_modifiers = {
        match.start("qualification") for match in _NO_PROFESSIONAL_EQUIPMENT.finditer(text)
    }
    return any(
        match.start() not in equipment_modifiers
        and not _EXPERIENTIAL_SESSION.match(text, match.start())
        for match in ASSURANCE.finditer(text)
    )
