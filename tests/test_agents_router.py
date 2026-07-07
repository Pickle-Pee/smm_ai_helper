from app.routers.agents import _normalize_legacy_answers


def test_normalize_legacy_answers_splits_channels_string():
    assert _normalize_legacy_answers(
        {
            "channels": "Telegram, VK,  Threads ",
            "topic": "AI",
        }
    ) == {
        "channels": ["Telegram", "VK", "Threads"],
        "topic": "AI",
    }


def test_normalize_legacy_answers_keeps_non_string_channels_unchanged():
    channels = ["Telegram", "VK"]

    assert _normalize_legacy_answers({"channels": channels}) == {
        "channels": channels,
    }


def test_normalize_legacy_answers_does_not_mutate_original_answers():
    answers = {"channels": "Telegram, VK"}

    normalized = _normalize_legacy_answers(answers)

    assert answers == {"channels": "Telegram, VK"}
    assert normalized == {"channels": ["Telegram", "VK"]}
