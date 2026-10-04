"""Visible action shortening must preserve the full callback command."""
import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from bot.handlers import chat


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("Сделать аудит", "Сделать аудит", id="short"),
        pytest.param("Я" * 30, "Я" * 30, id="exact-limit"),
        pytest.param("Я" * 31, "Я" * 29 + "…", id="limit-plus-one"),
        pytest.param("ОченьОченьОченьОченьОченьДлинноеСлово", "ОченьОченьОченьОченьОченьДлин…", id="long-token"),
        pytest.param("Составить план продвижения продукта на месяц", "Составить план продвижения…", id="live-promotion"),
        pytest.param("Сгенерировать 10 постов для бизнеса", "Сгенерировать 10 постов для…", id="live-posts"),
        pytest.param("Сформулировать оффер и написать варианты", "Сформулировать оффер и…", id="live-offer"),
        pytest.param("а" * 14 + " " + "б" * 14 + " дальше", "а" * 14 + " " + "б" * 14 + "…", id="whole-word-exact-prefix"),
        pytest.param("  Сделать\t\nаудит   ", "Сделать аудит", id="short-whitespace"),
        pytest.param("\tСделать   подробный\nплан\tпродвижения  ", "Сделать подробный план…", id="long-whitespace"),
        pytest.param("🚀 Сделать подробный план продвижения", "🚀 Сделать подробный план…", id="non-bmp-emoji-sentence"),
        pytest.param("🚀" * 31, "🚀" * 29 + "…", id="non-bmp-emoji-token"),
        pytest.param("е\u0301" * 16, ("е\u0301" * 16)[:29] + "…", id="combining-codepoints"),
    ],
)
def test_visible_label_boundaries(text, expected):
    assert chat.ACTION_LABEL_MAX_CHARS == 30
    label = chat._short_action_label(text)
    assert label == expected
    assert len(label) <= chat.ACTION_LABEL_MAX_CHARS
    label.encode("utf-8")


@pytest.mark.parametrize("separator", [",", ".", ";", ":", "!", "?"])
def test_separator_before_shortened_boundary_is_removed(separator):
    text = f"Сделать аудит{separator} оченьподробныйпланпродвижения"
    assert chat._short_action_label(text) == "Сделать аудит…"


def test_explicit_limit_reserves_ellipsis():
    assert chat._short_action_label("Сделать аудит", limit=12) == "Сделать…"


@pytest.fixture
def action_store(monkeypatch):
    store = {}
    monkeypatch.setattr(chat, "ACTION_STORE", store)
    return store


@pytest.mark.parametrize(
    "original",
    [
        "Сгенерировать 10 постов для бизнеса и добавить CTA",
        " \tСделать   подробный\nплан продвижения\t ",
    ],
)
def test_keyboard_and_callback_preserve_full_action(monkeypatch, action_store, original):
    actor = 123
    full = original.strip()
    markup = chat._actions_keyboard(actor, [{"text": original}])
    button = markup.inline_keyboard[0][0]
    expected_key = hashlib.sha256(f"{actor}:{full}".encode("utf-8")).hexdigest()[:12]
    assert button.text != full
    assert button.text.endswith("…")
    assert len(button.text) <= chat.ACTION_LABEL_MAX_CHARS
    assert button.callback_data == f"action:{expected_key}"
    assert action_store == {str(actor): {expected_key: full}}

    backend = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", backend)
    message = SimpleNamespace()
    callback = SimpleNamespace(data=button.callback_data, from_user=SimpleNamespace(id=actor),
                               message=message, answer=AsyncMock())
    asyncio.run(chat.on_action(callback))
    backend.assert_awaited_once_with(message, full, actor_id=actor)
    callback.answer.assert_awaited_once_with("Ок, выполняю…")


def test_same_visible_prefix_keeps_separate_callback_identity(monkeypatch, action_store):
    actor = 456
    full_actions = [
        "Сгенерировать 10 постов для бизнеса B2B",
        "Сгенерировать 10 постов для бизнеса B2C",
    ]
    markup = chat._actions_keyboard(actor, [{"text": text} for text in full_actions])
    buttons = [row[0] for row in markup.inline_keyboard]
    assert len(buttons) == 2
    assert buttons[0].text == buttons[1].text
    assert buttons[0].text.endswith("…")
    assert buttons[0].callback_data != buttons[1].callback_data
    expected_store = {
        hashlib.sha256(f"{actor}:{text}".encode("utf-8")).hexdigest()[:12]: text
        for text in full_actions
    }
    assert action_store == {str(actor): expected_store}
    for button, full in zip(buttons, full_actions):
        assert action_store[str(actor)][button.callback_data.split(":", 1)[1]] == full

    backend = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", backend)
    message = SimpleNamespace()

    async def click_each():
        for button in buttons:
            callback = SimpleNamespace(data=button.callback_data, from_user=SimpleNamespace(id=actor),
                                       message=message, answer=AsyncMock())
            await chat.on_action(callback)

    asyncio.run(click_each())
    assert backend.await_args_list == [call(message, text, actor_id=actor) for text in full_actions]
