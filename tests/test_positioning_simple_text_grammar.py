"""Portable text syntax remains separate from full semantic acceptance."""
from jsonschema import Draft202012Validator

from tests.test_positioning_support_selection import fixture, output, qualitative


def test_free_text_uses_the_existing_simple_pattern_once_per_schema():
    from app.module_execution.executors.provider_schema import nodes
    f = fixture()
    assert [n["pattern"] for n in nodes(f[1]) if "pattern" in n] == ["^[^0-9]*$"]


def test_digit_free_prose_does_not_require_artificial_punctuation_or_ascii_alphabet():
    f = fixture(("offer",))
    payload = output(f)
    payload["outputs"]["offer"]["text"] = qualitative("Создать понятное предложение — café")
    assert Draft202012Validator(f[1]).is_valid(payload)
