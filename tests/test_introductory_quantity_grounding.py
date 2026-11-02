"""An introductory modifier cannot hide a counted session or visit."""
import pytest

from app.module_execution.executors.numeric_quantity import has_numeric_quantity


@pytest.mark.parametrize("text", ["A single introductory session.",
    "One introductory visit.", "одно вводное занятие", "одном вводном занятии",
    "двумя вводными занятиями", "one short introductory session"])
def test_introductory_count_is_detected(text):
    assert has_numeric_quantity(text)


@pytest.mark.parametrize("text", ["An introductory session.", "вводное занятие",
    "one should discuss introductory sessions", "one; introductory session",
    "one entirely unrelated introductory session"])
def test_existing_word_gap_and_modifier_boundaries_remain(text):
    assert not has_numeric_quantity(text)
