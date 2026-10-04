"""Plain-text assistant contract regressions; providers and Telegram stay offline."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.assistant_normalizer import normalize_assistant_payload, normalize_plain_text
from app.services.assistant_core import _fallback_assistant_payload
from app.services.chat_response_service import ChatResponseService
from app.services import chat_response_service, qc_shortener
from bot.rendering import send_text


REPRO = "**Продвижение:**\nПомогу выбрать каналы.\n\n**Реклама:**\nПомогу проверить гипотезы."
PLAIN_REPRO = "Продвижение:\nПомогу выбрать каналы.\n\nРеклама:\nПомогу проверить гипотезы."


@pytest.mark.parametrize("raw,expected", [
    ("**Текст**", "Текст"), ("__Текст__", "Текст"),
    ("*Текст*", "Текст"), ("_Текст_", "Текст"), ("`CPL`", "CPL"),
    ("### Заголовок", "Заголовок"), ("## Заголовок", "Заголовок"),
    ("# Заголовок", "Заголовок"), (REPRO, PLAIN_REPRO),
    ("### Анализ\n- **Реклама**\n• _Каналы_", "Анализ\n- Реклама\n• Каналы"),
])
def test_formatting_becomes_plain_text(raw, expected):
    assert normalize_assistant_payload({"reply": raw})["reply"] == expected


@pytest.mark.parametrize("delimiter", ["**", "*", "__", "_", "`"])
@pytest.mark.parametrize("body,expected", [
    ("Сайт: https://example.com", "Сайт: https://example.com"),
    ("[Подробнее](https://example.com)", "Подробнее — https://example.com"),
    ("Сайт: https://example.com/path).", "Сайт: https://example.com/path)."),
    ("Сайт: https://example.com/a_b?q=a*b&x=y_z#part",
     "Сайт: https://example.com/a_b?q=a*b&x=y_z#part"),
])
def test_formatting_span_ending_in_url(delimiter, body, expected):
    output = normalize_plain_text(f"{delimiter}{body}{delimiter}")
    assert output == expected
    assert normalize_plain_text(output) == output


@pytest.mark.parametrize("text", [
    "https://example.com/a_b",
    "https://example.com/a_b?q=a*b&x=y_z#part",
    "https://example.com/path**", "https://example.com/path__",
    "https://example.com/path*", "https://example.com/path_",
    "https://example.com/path`", "https://example.com/path).",
    "Сайт: https://example.com/path**",
    "**Незакрытый\nСайт: https://example.com/path**",
    '<b title="**">Текст</b> Сайт: https://example.com/path**',
    "https://example.com/other** Сайт: https://example.com/path**",
])
def test_literal_url_suffix_is_preserved_and_idempotent(text):
    assert normalize_plain_text(text) == text
    assert normalize_plain_text(normalize_plain_text(text)) == text


@pytest.mark.parametrize("text", [
    "2 * 3 = 6", "A_B тест", "https://example.com/a_b", "#1 канал",
    "CPL = 500 ₽", "C++", "email@example.com", "**Незакрытый",
    "https://example.com/a_b?q=a*b&other=x_y#section",
    "https://example.com/?q=[x](y)",
    '<a href="[x](https://example.com)">Текст</a>',
    "<b>Текст</b> & <не тег>",
])
def test_plain_content_is_preserved(text):
    assert normalize_assistant_payload({"reply": text})["reply"] == text


@pytest.mark.parametrize("url", [
    "https://example.com", "https://example.com/a_b?q=a*b&x=y_z#part",
    "https://example.com/path_(nested_(value))?q=a_b&x=2",
])
def test_markdown_link_preserves_label_and_complete_url(url):
    output = normalize_assistant_payload({"reply": f"[Подробнее]({url})"})["reply"]
    assert output in (f"Подробнее — {url}", f"Подробнее ({url})")


def test_adjacent_format_markers_do_not_merge_text_into_url():
    output = normalize_assistant_payload({"reply": "**https://example.com/**tail**"})["reply"]
    assert output == "**https://example.com/**tail**"


def test_follow_up_and_actions_share_plain_text_contract():
    output = ChatResponseService.normalize({
        "reply": "**Ответ**", "follow_up_question": "**Продолжить**?",
        "actions": [{"type": "suggestion", "text": "**Проверить** `CPL`"}],
    })
    assert output["reply"] == "Ответ"
    assert output["follow_up_question"] == "Продолжить?"
    assert output["actions"][0] == {"type": "suggestion", "text": "Проверить CPL"}


def test_non_json_fallback_is_normalized_at_shared_boundary():
    output = ChatResponseService.normalize(_fallback_assistant_payload("**Ответ**\nТекст"))
    assert output["reply"] == "Ответ\nТекст"


@pytest.mark.parametrize("boundary", [ChatResponseService.normalize, _fallback_assistant_payload])
def test_complete_format_pair_is_removed_before_reply_length_limit(boundary):
    raw = "**" + "Я" * 1700 + "**"
    output = boundary({"reply": raw}) if boundary is ChatResponseService.normalize else boundary(raw)
    assert "*" not in output["reply"]
    assert len(output["reply"]) <= 1600
    assert output["reply"].startswith("Я" * 100)


@pytest.mark.parametrize("mode", ["success", "malformed", "not_dict", "empty", "provider_exception"])
def test_qc_result_and_all_fallbacks_keep_plain_text(monkeypatch, mode):
    async def generate(**_kwargs):
        return {"reply": "**Исходный ответ**", "actions": []}

    async def provider(**_kwargs):
        if mode == "provider_exception":
            raise RuntimeError("provider unavailable")
        content = {"success": json.dumps({"reply": "**Короткий ответ**"}),
                   "malformed": "not json", "not_dict": "[]", "empty": '{"reply": ""}'}[mode]
        return content, {}

    monkeypatch.setattr(chat_response_service, "generate_assistant_reply", generate)
    monkeypatch.setattr(qc_shortener, "openai_chat", provider)
    result = asyncio.run(ChatResponseService().generate(
        user_message="Привет", summary="", facts_json={}, last_messages=[]))
    assert result["reply"] == ("Короткий ответ" if mode == "success" else "Исходный ответ")
    if mode != "success":
        assert any(w.startswith("qc_failed:") for w in result["warnings"])


def test_unexpected_qc_exception_keeps_real_normalization(monkeypatch):
    async def generate(**_kwargs):
        return {"reply": REPRO, "follow_up_question": "**Продолжить**?"}

    async def broken_qc(_payload):
        raise RuntimeError("unexpected QC failure")

    monkeypatch.setattr(chat_response_service, "generate_assistant_reply", generate)
    monkeypatch.setattr(chat_response_service, "qc_shorten", broken_qc)
    result = asyncio.run(ChatResponseService().generate(
        user_message="Привет", summary="", facts_json={}, last_messages=[]))
    assert result["reply"] == PLAIN_REPRO
    assert result["follow_up_question"] == "Продолжить?"


def test_normalize_then_delivery_preserves_long_text_and_utf16_chunk_limit():
    raw = "**Реклама 🙂**\n" * 1000
    normalized = normalize_assistant_payload({"reply": raw})["reply"]
    msg = SimpleNamespace(answer=AsyncMock())
    asyncio.run(send_text(msg, normalized))
    chunks = [call.args[0] for call in msg.answer.call_args_list]
    assert "".join(chunks) == "Реклама 🙂\n" * 1000
    assert len(chunks) > 1
    assert all(len(chunk.encode("utf-16-le")) // 2 <= 3500 for chunk in chunks)
    assert all(call.kwargs["parse_mode"] is None for call in msg.answer.call_args_list)
