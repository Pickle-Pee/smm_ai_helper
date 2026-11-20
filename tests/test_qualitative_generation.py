"""Regular generation language excludes complete finite cardinal tokens."""
import re
from itertools import product

import pytest

from app.module_execution.executors.numeric_quantity import _CARDINALS, has_numeric_quantity
from app.module_execution.executors.qualitative_generation import (
    GENERATION_COUNT_WORDS, QUALITATIVE_GENERATION_PATTERN)


PATTERN = re.compile(QUALITATIVE_GENERATION_PATTERN)


def test_regular_pattern_excludes_observed_count_forms_without_splitting_words():
    for cardinal in sorted(GENERATION_COUNT_WORDS):
        mixed = "".join(character.upper() if index % 2 else character
                        for index, character in enumerate(cardinal))
        for word in (cardinal, cardinal.upper(), cardinal.title(), mixed):
            for text in (word, "Compare " + word + " options", "Text\n«" + word + "»\nafter"):
                assert PATTERN.fullmatch(text) is None, text
        assert PATTERN.fullmatch("prefix" + cardinal + "suffix") is not None


@pytest.mark.parametrize("text", [
    "Разработать два варианта тестовых сообщений: акцент на обратной связи и акцент на практике.",
    "Compare two short options", "Сравнить ДвА варианта", "Протестировать\nдве гипотезы",
    "Текст\nи два варианта\nсообщений", "два-варианта", "двух вариантов",
    "Разработать 2 варианта", "Text\n2\nafter", "два\n", "two\n",
])
def test_saved_failure_boundaries_and_multiline_quantities_are_rejected(text):
    assert PATTERN.fullmatch(text) is None


@pytest.mark.parametrize("text", [
    "Разработать варианты сообщений", "Compare alternatives", "someone has feedback",
    "Первый шаг — проверить интерес", "двадцатый вариант", "Отзывы\nи практика.",
    "Сравнить варианты с акцентом на обратной связи и практике.",
    "Text\nafter\n", "Отзывы, практика; сообщения — интерес!", "двац", "ones", "one of the options",
])
def test_ordinary_words_prefixes_suffixes_and_punctuation_remain_allowed(text):
    assert PATTERN.fullmatch(text) is not None


def test_regular_pattern_matches_explicit_token_reference_on_combinations():
    tokens = ("one", "один", "вариант", "feedback", "someone", "двац", "од", "single", "twofold")
    for left, separator, right in product(tokens, ("", " ", "-", "\n", "_", "«"), tokens):
        text = left + separator + right
        words = re.findall("[A-Za-zА-Яа-яЁё]+", text)
        expected = all(word.lower() not in GENERATION_COUNT_WORDS for word in words)
        assert (PATTERN.fullmatch(text) is not None) == expected, text


def test_long_prose_punctuation_and_near_matches_are_bounded():
    for text in (("Проверить реакцию на сообщение. " * 140)[:4000],
                 ".,;!?—\n " * 500,
                 "одиннадцатый " * 300,
                 "a" * 4000):
        assert len(text) <= 4000
        assert PATTERN.fullmatch(text) is not None
        assert PATTERN.fullmatch(text[:-1] + "2") is None


def test_pattern_uses_regular_constructs_and_only_outer_anchors():
    assert len(QUALITATIVE_GENERATION_PATTERN) < 2000
    assert QUALITATIVE_GENERATION_PATTERN.count("$") == 1
    assert re.sub(r"\[\^", "[", QUALITATIVE_GENERATION_PATTERN).count("^") == 1
    for unsupported in ("(?=", "(?!", "(?<=", "(?<!", "(?i", r"\b", r"\w", r"\d"):
        assert unsupported not in QUALITATIVE_GENERATION_PATTERN
    assert re.search(r"\\[1-9]", QUALITATIVE_GENERATION_PATTERN) is None


def test_unicode_digits_remain_the_canonical_guards_responsibility():
    # As with the prior ASCII-only generation pattern, this is deliberately
    # not a general Unicode numerical guarantee.
    assert PATTERN.fullmatch("Сравнить ٢ варианта") is not None


def test_full_canonical_vocabulary_remains_authoritative_outside_generation_filter():
    assert GENERATION_COUNT_WORDS < _CARDINALS
    for cardinal in _CARDINALS:
        for word in (cardinal, cardinal.upper()):
            assert has_numeric_quantity(word + " варианта"), word
    assert PATTERN.fullmatch("Сравнить три варианта") is not None
    assert has_numeric_quantity("Сравнить три варианта")
