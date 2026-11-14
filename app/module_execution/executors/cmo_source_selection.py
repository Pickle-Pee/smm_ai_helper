"""Explicit CMO whole-source choices, never inferred citations or authority."""
from copy import deepcopy
import json
import re

from app.module_execution.errors import ModuleExecutionContractError
from .common import EvidenceSourceClass
from .downstream_fidelity import typed_literal_sources
from .numeric_quantity import has_numeric_quantity
from .qualitative_generation import QUALITATIVE_GENERATION_PATTERN

MAX_SOURCE_CHOICES = 64
MAX_SOURCE_BYTES = 16384
SOURCE_ROLES = frozenset({"product_truth", "confirmed_business_fact", "existing_proof"})
_FIELDS = {"text", "evidence_id", "evidence_key", "input_key", "source_class"}
# Reserve the standalone namespace, not words ending in "source" (Resource:).
# A complete marker fragment remains technical syntax even with glued text.
_RESERVED_SOURCE = re.compile(r"\bSOURCE:|SOURCE:e[0-9]{3}", re.I)
_QUALITATIVE = re.compile(QUALITATIVE_GENERATION_PATTERN)
SOURCE_ITEMS_DESCRIPTION = (
    "Items are qualitative strategic prose OR exact listed SOURCE tokens. "
    "No digits in prose; digits are allowed ONLY inside exact SOURCE tokens. "
    "For current owner/demo facts choose SOURCE or omit the fact. "
    "Keep proposed use or interpretation in a separate qualitative item."
)


def contains_reserved_source_syntax(text):
    return bool(_RESERVED_SOURCE.search(text))


def _fail():
    raise ModuleExecutionContractError("Invalid CMO explicit source selection") from None


def source_selection_catalog(evidence, evidence_aliases):
    """Complete typed local strings only; use the existing CMO alias bijection."""
    evidence = tuple(evidence)
    if type(evidence_aliases) is not dict:
        _fail()
    identities = [item.record.evidence_id for item in evidence]
    if (len(set(identities)) != len(identities)
            or set(identities) != set(evidence_aliases.values())
            or len(evidence_aliases) != len(identities)):
        _fail()
    aliases = {identity: key for key, identity in evidence_aliases.items()}
    local = {item.record.evidence_id: item for item in evidence}
    catalog = {}
    for item in evidence:
        text = item.value
        owner, demo = typed_literal_sources((item.record.evidence_id,), local)
        if (not (owner or demo) or type(text) is not str
                or not 1 <= len(text) <= 4000 or not text.strip() or text != text.strip()
                or has_numeric_quantity(text) or _QUALITATIVE.fullmatch(text) is None
                or contains_reserved_source_syntax(text)):
            continue
        key = aliases[item.record.evidence_id]
        catalog["SOURCE:" + key] = {"text": text, "evidence_id": item.record.evidence_id,
            "evidence_key": key, "input_key": item.input_key,
            "source_class": EvidenceSourceClass.FIRST_PARTY.value}
    catalog = dict(sorted(catalog.items()))
    validate_source_catalog(catalog, evidence_aliases)
    return catalog


def validate_source_catalog(catalog, evidence_aliases):
    if (type(evidence_aliases) is not dict or type(catalog) is not dict
            or len(catalog) > MAX_SOURCE_CHOICES):
        _fail()
    for marker, row in catalog.items():
        if type(marker) is not str or type(row) is not dict or set(row) != _FIELDS:
            _fail()
        key, text = row["evidence_key"], row["text"]
        if (type(key) is not str or re.fullmatch(r"e[0-9]{3}", key) is None
                or marker != "SOURCE:" + key or key not in evidence_aliases
                or row["evidence_id"] != evidence_aliases[key]
                or type(row["input_key"]) is not str or row["input_key"] not in SOURCE_ROLES
                or row["source_class"] != EvidenceSourceClass.FIRST_PARTY.value
                or type(text) is not str or not 1 <= len(text) <= 4000
                or not text.strip() or text != text.strip()
                or has_numeric_quantity(text) or _QUALITATIVE.fullmatch(text) is None
                or contains_reserved_source_syntax(text)):
            _fail()
    try:
        if len(json.dumps(catalog, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_SOURCE_BYTES:
            _fail()
    except (TypeError, ValueError, UnicodeError):
        _fail()


def source_text_schema(field, maximum, catalog):
    """Keep the productive prose branch exact; marker enums contain digits."""
    if (type(field) is not dict
            or set(field) - {"type", "minLength", "maxLength", "pattern", "title", "description"}
            or field.get("type") != "string" or field.get("minLength") != 1
            or field.get("maxLength") != maximum or field.get("pattern") != QUALITATIVE_GENERATION_PATTERN):
        _fail()
    markers = sorted(key for key, row in catalog.items() if len(row["text"]) <= maximum)
    if not markers:
        return deepcopy(field)
    return {"description": (
        "Choose qualitative prose under the no-digit rule OR one exact listed SOURCE token. "
        "Token digits are technical selectors, not strategic quantities. "
        "For a current owner/demo fact choose SOURCE or omit it; "
        "put prospective use or interpretation in a separate qualitative leaf."
    ), "anyOf": [deepcopy(field), {"type": "string", "enum": markers, "description": (
        "Exact whole-source selector, for example " + markers[0] + ". "
        "Digits are permitted ONLY as part of an exact listed token. "
        "It renders the complete source and selects its evidence on THIS output. "
        "Do not append explanation, interpretation or claimed effects."
    )}]}


def reject_reserved_marker(text):
    if contains_reserved_source_syntax(text):
        _fail()


def render_source_leaf(text, maximum, catalog, *, allowed):
    """One exact explicit choice selects its source on this output, once only."""
    if allowed and text in catalog:
        row = catalog[text]
        if len(row["text"]) > maximum:
            _fail()
        return row["text"], row["evidence_id"]
    reject_reserved_marker(text)
    return text, None
