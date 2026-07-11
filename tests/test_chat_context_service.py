import asyncio
from datetime import datetime

import app.services.chat_context_service as chat_context_module
from app.models import Conversation
from app.services.chat_context_service import ChatContextService


class FakeDbSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


def test_update_context_updates_facts_summary_timestamp_and_commits(monkeypatch):
    db_session = FakeDbSession()
    conversation = Conversation(
        user_id="user-1",
        summary="old summary",
        facts_json={"brand_name": "Old"},
    )
    fixed_now = datetime(2026, 7, 9, 12, 0, 0)

    async def fake_extract_facts(current_facts, last_user_message, url_summaries):
        assert current_facts == {"brand_name": "Old"}
        assert last_user_message == "Новое сообщение"
        assert url_summaries == [{"title": "Example"}]
        return {"facts": {"brand_name": "New", "audience": "Experts"}}

    async def fake_update_summary(current_summary, last_messages):
        assert current_summary == "old summary"
        assert last_messages == [
            {"role": "user", "text": "Старое сообщение"},
            {"role": "user", "text": "Новое сообщение"},
        ]
        return "new summary"

    class FixedDatetime:
        @staticmethod
        def utcnow():
            return fixed_now

    monkeypatch.setattr(chat_context_module, "extract_facts", fake_extract_facts)
    monkeypatch.setattr(chat_context_module, "update_summary", fake_update_summary)
    monkeypatch.setattr(chat_context_module, "datetime", FixedDatetime)

    result = asyncio.run(
        ChatContextService(db_session).update_context(
            conversation=conversation,
            user_message="Новое сообщение",
            last_messages=[
                {"role": "user", "text": "Старое сообщение"},
                {"role": "user", "text": "Новое сообщение"},
            ],
            url_summaries=[{"title": "Example"}],
        )
    )

    assert conversation.facts_json == {"brand_name": "New", "audience": "Experts"}
    assert conversation.summary == "new summary"
    assert conversation.updated_at == fixed_now
    assert db_session.commits == 1
    assert result.summary == "new summary"
    assert result.facts_json == {"brand_name": "New", "audience": "Experts"}


def test_update_context_uses_safe_defaults(monkeypatch):
    db_session = FakeDbSession()
    conversation = Conversation(user_id="user-1", summary=None, facts_json=None)

    async def fake_extract_facts(current_facts, last_user_message, url_summaries):
        assert current_facts == {}
        assert last_user_message == "Сообщение"
        assert url_summaries is None
        return {"facts": {}}

    async def fake_update_summary(current_summary, last_messages):
        assert current_summary == ""
        assert last_messages == []
        return ""

    monkeypatch.setattr(chat_context_module, "extract_facts", fake_extract_facts)
    monkeypatch.setattr(chat_context_module, "update_summary", fake_update_summary)

    result = asyncio.run(
        ChatContextService(db_session).update_context(
            conversation=conversation,
            user_message="Сообщение",
            last_messages=[],
        )
    )

    assert conversation.facts_json == {}
    assert conversation.summary == ""
    assert db_session.commits == 1
    assert result.summary == ""
    assert result.facts_json == {}
