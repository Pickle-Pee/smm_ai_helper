"""Bind provider generation to the language of the owner's request.

Live multi-domain acceptance (15.11.2026) returned mostly English CMO/EXPERIMENTS
prose for Russian requests, kind labels and schema keys inside prose, and a count
compound («двухвариантных») that the unchanged numeric guard rejects. All of them
are generation problems, so they are closed where generation is constrained: the
schema sent to the provider. For a Russian request

- free prose may consist of Cyrillic words and listed punctuation only (no Latin
  letter, no digit of any script, no "_"),
- count compounds are excluded as word prefixes, matching the numeric guard,
- closed server sentences and relation keys are offered only in Russian.

This is a narrowing projection: every value the provider can produce is still valid
for the unchanged wire schema, decoder, canonical validators and Quality Gates.
Owner texts are never removed or altered. Other request languages are untouched.
"""
from copy import deepcopy
import json
import re

from .cmo_demo_plans import DEMO_FREE_PATTERN, DEMO_STEMS, DEMO_WORDS, EQUIPMENT_STEMS
from .common import plain
from .provider_schema import nodes
from .qualitative_generation import (
    GENERATION_COUNT_WORDS, QUALITATIVE_GENERATION_PATTERN, allowed_word_pattern, generation_pattern,
)

_CYRILLIC = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
_CYRILLIC_LETTER = re.compile("[А-Яа-яЁё]")
_LATIN_LETTER = re.compile("[A-Za-z]")
# Cardinal stems that form count compounds with a unit («двухвариантный»). The
# numeric guard recognizes cardinal+unit concatenations; generation avoids the
# whole word family instead of guessing the unit.
RU_COUNT_PREFIXES = ("двух", "трёх", "трех", "четырёх", "четырех")
# A positive list of separators. A negated class admits every other Unicode character:
# the model wrote a time with Arabic-Indic digits («۱۸:۰۰») when ASCII digits were excluded.
# ASCII hyphen stays last so that it needs no escape.
RU_SEPARATOR = "[ .,;:!?()«»\"'/…‐‑–—-]"
_RU_COUNT_WORDS = frozenset(word for word in GENERATION_COUNT_WORDS if not set(word) - set(_CYRILLIC))
_RU_DEMO_WORDS = frozenset(word for word in DEMO_WORDS if not set(word) - set(_CYRILLIC))


def _ru_pattern(words, prefixes):
    stems = tuple(stem for stem in prefixes if not set(stem) - set(_CYRILLIC))
    word = allowed_word_pattern(words, stems + RU_COUNT_PREFIXES, alphabet=_CYRILLIC, word_character="[А-Яа-яЁё]")
    # Only Cyrillic words and listed punctuation exist: no Latin letter, no digit of any
    # script, no underscore and no other symbol can be generated.
    return generation_pattern(word, separator=RU_SEPARATOR)


# Changing either pattern requires a new provider capability probe (see
# tests/test_provider_language.py and docs/development/provider-language-projection.md).
# EXPERIMENTS prose closes demo vocabulary too: on 33e6918 the model embedded the owner's demo
# sentence in a longer free text and the unchanged downstream check rejected the node
# (DEMONSTRATION_ASSERTION_REQUIRES_SOURCE). A demo fact is an owner source, never free prose.
RU_QUALITATIVE_PATTERN = _ru_pattern(_RU_COUNT_WORDS | _RU_DEMO_WORDS, DEMO_STEMS)
RU_CMO_PATTERN = _ru_pattern(_RU_COUNT_WORDS | _RU_DEMO_WORDS, DEMO_STEMS + EQUIPMENT_STEMS)
_RU_PATTERNS = {QUALITATIVE_GENERATION_PATTERN: RU_QUALITATIVE_PATTERN, DEMO_FREE_PATTERN: RU_CMO_PATTERN}


def _strings(value):
    if isinstance(value, str):
        yield value
        if value.lstrip().startswith(("{", "[")):
            try:
                yield from _strings(json.loads(value))
            except ValueError:
                pass
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _request_strings(request):
    return set(_strings([request.objective, plain(request.context_packet),
                         [plain(upstream) for upstream in request.upstream_results]]))


def request_language(request):
    """Return "ru" when the owner's own inputs are predominantly Cyrillic, else None."""
    packet = request.context_packet
    owned = [request.objective, *packet.constraints,
             *(fact.value for fact in (*packet.relevant_project_context, *packet.known_facts)
               if fact.authorized and isinstance(fact.value, str))]
    text = " ".join(value for value in owned if isinstance(value, str))
    cyrillic, latin = len(_CYRILLIC_LETTER.findall(text)), len(_LATIN_LETTER.findall(text))
    return "ru" if cyrillic > latin else None


def _prose(value):
    return any(character.isspace() for character in value)


def language_projection(schema, request):
    """Narrow a provider schema to the request language; identity when it is not Russian."""
    if request_language(request) != "ru":
        return schema
    result = deepcopy(schema)
    protected = _request_strings(request)
    for node in nodes(result):
        if node.get("pattern") in _RU_PATTERNS:
            node["pattern"] = _RU_PATTERNS[node["pattern"]]
        values = node.get("enum")
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            continue
        russian_keys = [value for value in values if value.endswith("_ru")]
        english_keys = [value for value in values if value.endswith("_en")]
        if russian_keys and len(russian_keys) == len(english_keys) == len(values) / 2:
            node["enum"] = russian_keys
            continue
        # Server sentences come in translated pairs. Anything present in the request
        # (owner texts, quotes, upstream statements) is never a candidate for removal.
        closed = [value for value in values if _prose(value) and value not in protected]
        russian = [value for value in closed if _CYRILLIC_LETTER.search(value)]
        english = [value for value in closed if not _CYRILLIC_LETTER.search(value) and _LATIN_LETTER.search(value)]
        if russian and len(russian) == len(english):
            node["enum"] = [value for value in values if value not in english]
    for node in nodes(result):
        items = node.get("items")
        if (node.get("type") == "array" and isinstance(items, dict) and isinstance(items.get("enum"), list)
                and node.get("minItems", 0) > len(items["enum"])):
            return schema  # Never send an unsatisfiable schema; keep the unprojected one.
    return result


LANGUAGE_GUIDANCE = {
    "ru": ("Write every free-text field in Russian. Free text accepts Cyrillic words and ordinary "
           "punctuation only: Latin letters, digits and underscores cannot be generated. Never start a "
           "text with a kind label or a field name. Name channels and brands in Russian spelling or "
           "describe them. Never restate or spell out a time, date, price or count in free text: refer "
           "to it as the owner's complete terms. Never quote or restate an owner text or a demonstration "
           "material inside free text: owner wording appears only through the listed exact choices. "
           "Free text cannot spell «демонстрационный» or «демонстрация» at all: call the owner's "
           "demonstration material «предоставленный образец» and do not say what it shows or proves. "
           "When a required input is the owner's demonstration sentence, choose it from the listed exact "
           "choices and select that source on the first output."),
}


def with_output_language(data, request):
    """Tell the model which language the constrained free text accepts (data, not instructions)."""
    language = request_language(request)
    if language not in LANGUAGE_GUIDANCE:
        return data
    return {**data, "output_language": language, "output_language_guidance": LANGUAGE_GUIDANCE[language]}
