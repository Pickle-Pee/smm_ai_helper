"""Small CMO generation subset, never product authority or entailment checking."""
import json
import re

from app.module_execution.errors import ModuleExecutionContractError
from .common import EvidenceSourceClass
from .numeric_quantity import has_numeric_quantity
from .qualitative_generation import GENERATION_COUNT_WORDS
from .regular_word_generation import LETTERS, SEPARATOR, allowed_word_pattern

FORMAT_PREFIXES = ("персональн", "индивидуальн", "стандартизован", "стандартизирован")
FORMAT_WORDS = frozenset(("personal", "personalized", "personalised", "individual",
                          "individualized", "individualised", "standardized", "standardised"))
MAX_OWNER_QUOTE_ENTRIES = 64
MAX_OWNER_QUOTE_BYTES = 16384
_WORDS = re.compile(f"[{LETTERS}]+")
_WORD_PATTERN = allowed_word_pattern(GENERATION_COUNT_WORDS | FORMAT_WORDS,
                                     prefixes=FORMAT_PREFIXES)
# Retain the proven outer-only two-word wrapper. Words are maximal and may end
# directly at the string boundary. The preceding one-word candidate imposed a
# terminal separator and returned an incomplete provider response; causation is
# unproved. Shared bounded definitions avoid repeating this larger pattern.
CMO_GENERATION_PATTERN = (
    "^" + SEPARATOR + "*(?:" + _WORD_PATTERN
    + "(?:" + SEPARATOR + "+" + _WORD_PATTERN + ")*)?" + SEPARATOR + "*$"
)
_PROSE = re.compile(CMO_GENERATION_PATTERN)
PROSE_DEFINITIONS = {4000: "CMOQualitativeText", 300: "CMOQualitativeItem"}


def prose_definitions():
    return {name: {"type": "string", "minLength": 1, "maxLength": maximum,
                   "pattern": CMO_GENERATION_PATTERN}
            for maximum, name in PROSE_DEFINITIONS.items()}


def _fail():
    raise ModuleExecutionContractError("Invalid CMO owner quotation catalog") from None


def contains_format_word(text):
    return any(word.lower() in FORMAT_WORDS or word.lower().startswith(FORMAT_PREFIXES)
               for word in _WORDS.findall(text))


def owner_quote_catalog(evidence):
    """Only complete string values already eligible for canonical owner proof.

    Ordinary prose is not an enum escape. Numerical source values remain solely
    in numeric_context. Never split, shorten, normalize or infer source roles.
    """
    evidence = tuple(evidence)
    entries = []
    for item in evidence:
        if (item.record.source_class is not EvidenceSourceClass.FIRST_PARTY
                or item.input_key not in {"product_truth", "confirmed_business_fact"}):
            continue
        text = item.value
        if (type(text) is str and 1 <= len(text) <= 4000 and text.strip()
                and contains_format_word(text) and not has_numeric_quantity(text)):
            entries.append({"support_id": item.record.evidence_id, "exact_quote": text})
    entries.sort(key=lambda row: (row["support_id"], row["exact_quote"]))
    validate_owner_catalog(entries, {item.record.evidence_id for item in evidence})
    return entries


def validate_owner_catalog(catalog, evidence_ids):
    if type(catalog) is not list or len(catalog) > MAX_OWNER_QUOTE_ENTRIES:
        _fail()
    seen = set()
    for row in catalog:
        if type(row) is not dict or set(row) != {"support_id", "exact_quote"}:
            _fail()
        identity, text = row["support_id"], row["exact_quote"]
        if (type(identity) is not str or not 1 <= len(identity) <= 128 or identity not in evidence_ids
                or type(text) is not str or not 1 <= len(text) <= 4000
                or not text.strip() or not contains_format_word(text)
                or has_numeric_quantity(text) or (identity, text) in seen):
            _fail()
        seen.add((identity, text))
    try:
        if len(json.dumps(catalog, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_OWNER_QUOTE_BYTES:
            _fail()
    except (TypeError, ValueError, UnicodeError):
        _fail()


def generation_field(field, maximum, catalog, *, original_pattern=None):
    """Project a proved bounded string without weakening any original bounds."""
    allowed = {"type", "minLength", "maxLength", "title", "description"}
    if original_pattern is not None:
        allowed.add("pattern")
    if (maximum not in PROSE_DEFINITIONS or type(field) is not dict
            or set(field) - allowed or field.get("type") != "string"
            or field.get("minLength") != 1 or field.get("maxLength") != maximum
            or (original_pattern is not None and field.get("pattern") != original_pattern)):
        _fail()
    prose = {"$ref": "#/$defs/" + PROSE_DEFINITIONS[maximum]}
    annotations = {key: field[key] for key in ("title", "description") if key in field}
    quotes = sorted({row["exact_quote"] for row in catalog if len(row["exact_quote"]) <= maximum})
    if not quotes:
        # Keep references bare: strict provider serializers may inline a $ref
        # with siblings. Annotations belong to the outer supported anyOf node.
        return {"anyOf": [prose], **annotations} if annotations else prose
    quote = {"type": "string", "minLength": 1, "maxLength": maximum}
    quote["enum"] = quotes
    return {"anyOf": [prose, quote], **annotations}


def validate_owner_quote_selection(statement, catalog, selected_evidence):
    """An enum never selects its source: absent explicit evidence flags reject."""
    for text in (statement["text"], *statement["items"]):
        if _PROSE.fullmatch(text):
            continue
        sources = {row["support_id"] for row in catalog if row["exact_quote"] == text}
        if not sources.intersection(selected_evidence):
            _fail()
