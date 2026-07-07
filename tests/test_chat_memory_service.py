import asyncio
from types import SimpleNamespace

from app.models import Conversation, Message
from app.services.chat_memory_service import ChatMemoryService


class FakeScalarResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeExecuteResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return FakeScalarResult(self.rows)


class FakeDbSession:
    def __init__(self, conversation=None, messages=None):
        self.conversation = conversation
        self.messages = messages or []
        self.added = []
        self.commits = 0
        self.executed = []

    async def get(self, model, key):
        assert model is Conversation
        if self.conversation and self.conversation.user_id == key:
            return self.conversation
        return None

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1

    async def execute(self, statement):
        self.executed.append(statement)
        return FakeExecuteResult(self.messages)


def test_get_or_create_conversation_returns_existing_conversation():
    conversation = Conversation(user_id="user-1", summary="old", facts_json={"brand": "x"})
    db_session = FakeDbSession(conversation=conversation)

    result = asyncio.run(
        ChatMemoryService(db_session).get_or_create_conversation("user-1")
    )

    assert result is conversation
    assert db_session.added == []
    assert db_session.commits == 0


def test_get_or_create_conversation_creates_missing_conversation():
    db_session = FakeDbSession()

    result = asyncio.run(
        ChatMemoryService(db_session).get_or_create_conversation("user-1")
    )

    assert result.user_id == "user-1"
    assert result.summary == ""
    assert result.facts_json == {}
    assert db_session.added == [result]
    assert db_session.commits == 1


def test_append_message_persists_message():
    db_session = FakeDbSession()

    result = asyncio.run(
        ChatMemoryService(db_session).append_message(
            user_id="user-1",
            role="user",
            text="Привет",
        )
    )

    assert isinstance(result, Message)
    assert result.user_id == "user-1"
    assert result.role == "user"
    assert result.text == "Привет"
    assert db_session.added == [result]
    assert db_session.commits == 1


def test_load_recent_messages_returns_chronological_context():
    db_session = FakeDbSession(
        messages=[
            SimpleNamespace(role="assistant", text="Ответ 2"),
            SimpleNamespace(role="user", text="Вопрос 1"),
        ]
    )

    result = asyncio.run(
        ChatMemoryService(db_session).load_recent_messages("user-1", limit=20)
    )

    assert result == [
        {"role": "user", "text": "Вопрос 1"},
        {"role": "assistant", "text": "Ответ 2"},
    ]
    assert len(db_session.executed) == 1
