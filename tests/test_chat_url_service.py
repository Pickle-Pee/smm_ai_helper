import asyncio
from types import SimpleNamespace

import app.services.chat_url_service as chat_url_service_module
from app.services.chat_url_service import ChatUrlService


class FakeUrlAnalyzer:
    result = None
    calls = []

    def __init__(self, db_session):
        self.db_session = db_session

    async def analyze(self, text):
        self.__class__.calls.append(
            {
                "db_session": self.db_session,
                "text": text,
            }
        )
        return self.__class__.result


def test_analyze_returns_used_url_context_when_url_data_exists(monkeypatch):
    db_session = object()
    url_data = SimpleNamespace(urls=["https://example.com"], url_summaries=[{"title": "Example"}])
    FakeUrlAnalyzer.result = url_data
    FakeUrlAnalyzer.calls = []

    monkeypatch.setattr(chat_url_service_module, "UrlAnalyzer", FakeUrlAnalyzer)
    monkeypatch.setattr(
        chat_url_service_module,
        "extract_urls",
        lambda text: ["https://example.com"],
    )

    result = asyncio.run(
        ChatUrlService(db_session).analyze("Посмотри https://example.com")
    )

    assert result.data is url_data
    assert result.used_url is True
    assert result.has_url_intent is True
    assert FakeUrlAnalyzer.calls == [
        {
            "db_session": db_session,
            "text": "Посмотри https://example.com",
        }
    ]


def test_analyze_returns_empty_context_when_no_url_data_and_no_url_intent(monkeypatch):
    db_session = object()
    FakeUrlAnalyzer.result = None
    FakeUrlAnalyzer.calls = []

    monkeypatch.setattr(chat_url_service_module, "UrlAnalyzer", FakeUrlAnalyzer)
    monkeypatch.setattr(chat_url_service_module, "extract_urls", lambda text: [])

    result = asyncio.run(ChatUrlService(db_session).analyze("Просто текст"))

    assert result.data is None
    assert result.used_url is False
    assert result.has_url_intent is False
    assert FakeUrlAnalyzer.calls == [
        {
            "db_session": db_session,
            "text": "Просто текст",
        }
    ]


def test_analyze_preserves_url_intent_when_analysis_returns_none(monkeypatch):
    db_session = object()
    FakeUrlAnalyzer.result = None
    FakeUrlAnalyzer.calls = []

    monkeypatch.setattr(chat_url_service_module, "UrlAnalyzer", FakeUrlAnalyzer)
    monkeypatch.setattr(
        chat_url_service_module,
        "extract_urls",
        lambda text: ["https://broken.example.com"],
    )

    result = asyncio.run(
        ChatUrlService(db_session).analyze("Посмотри https://broken.example.com")
    )

    assert result.data is None
    assert result.used_url is False
    assert result.has_url_intent is True
