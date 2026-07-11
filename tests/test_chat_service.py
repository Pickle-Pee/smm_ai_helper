import asyncio
from types import SimpleNamespace

import app.services.chat_service as chat_service_module
from app.services.chat_service import ChatService


class FakeMemoryService:
    def __init__(self):
        self.conversation = SimpleNamespace(user_id="user-1")
        self.append_calls = []
        self.recent_messages = [
            {"role": "user", "text": "Старый вопрос"},
            {"role": "assistant", "text": "Старый ответ"},
        ]
        self.load_calls = []

    async def get_or_create_conversation(self, user_id):
        assert user_id == "user-1"
        return self.conversation

    async def append_message(self, **kwargs):
        self.append_calls.append(kwargs)

    async def load_recent_messages(self, **kwargs):
        self.load_calls.append(kwargs)
        return self.recent_messages


class FakeUrlService:
    def __init__(self, context):
        self.context = context
        self.calls = []

    async def analyze(self, text):
        self.calls.append(text)
        return self.context


class FakeContextService:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def update_context(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeResponseService:
    def __init__(self, generated):
        self.generated = generated
        self.generate_calls = []
        self.normalize_calls = []

    async def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return dict(self.generated)

    def normalize(self, payload):
        self.normalize_calls.append(payload)
        return {
            "reply": payload.get("reply", ""),
            "follow_up_question": payload.get("follow_up_question"),
            "actions": payload.get("actions", []),
        }


class FakeImageService:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    async def generate_if_requested(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def build_service(
    *,
    memory=None,
    url_context=None,
    context_result=None,
    generated=None,
    image_result=None,
):
    memory = memory or FakeMemoryService()
    url_context = url_context or SimpleNamespace(
        data=None,
        used_url=False,
        has_url_intent=False,
    )
    context_result = context_result or SimpleNamespace(
        summary="summary",
        facts_json={"brand_name": "Brand"},
    )
    response = FakeResponseService(
        generated
        or {
            "reply": "Готовый ответ",
            "follow_up_question": None,
            "actions": [],
        }
    )
    image = FakeImageService(image_result)

    service = ChatService(
        db_session=object(),
        memory_service=memory,
        url_service=FakeUrlService(url_context),
        context_service=FakeContextService(context_result),
        response_service=response,
        image_service=image,
        request_id_factory=lambda: "request-1",
    )
    return service, memory, response, image


def test_handle_returns_blocked_response_and_stops_pipeline(monkeypatch):
    blocked_payload = {
        "reply": "Работаю только с маркетинговыми задачами",
        "follow_up_question": "Опиши маркетинговую задачу",
        "actions": [],
    }

    async def fake_scope_guard(text, use_llm_fallback):
        assert text == "Расскажи про погоду"
        assert use_llm_fallback is True
        return False, blocked_payload

    monkeypatch.setattr(chat_service_module, "scope_guard", fake_scope_guard)

    service, memory, response, image = build_service()

    result = asyncio.run(
        service.handle(user_id="user-1", text="Расскажи про погоду")
    )

    assert result == {
        "reply": "Работаю только с маркетинговыми задачами",
        "follow_up_question": "Опиши маркетинговую задачу",
        "actions": [],
        "debug": {
            "intent": "other",
            "used_url": False,
            "scope_blocked": True,
        },
        "image": None,
    }
    assert response.normalize_calls == [blocked_payload]
    assert response.generate_calls == []
    assert image.calls == []
    assert memory.load_calls == []
    assert memory.append_calls == [
        {"user_id": "user-1", "role": "user", "text": "Расскажи про погоду"},
        {
            "user_id": "user-1",
            "role": "assistant",
            "text": "Работаю только с маркетинговыми задачами",
        },
    ]


def test_handle_coordinates_standard_chat_flow(monkeypatch):
    async def fake_scope_guard(_text, use_llm_fallback):
        assert use_llm_fallback is True
        return True, None

    monkeypatch.setattr(chat_service_module, "scope_guard", fake_scope_guard)
    monkeypatch.setattr(chat_service_module, "detect_intent", lambda text: "content")

    service, memory, response, image = build_service()

    result = asyncio.run(
        service.handle(user_id="user-1", text="Напиши пост")
    )

    assert result == {
        "reply": "Готовый ответ",
        "follow_up_question": None,
        "actions": [],
        "debug": {"intent": "content", "used_url": False},
        "image": None,
    }
    assert memory.load_calls == [{"user_id": "user-1", "limit": 20}]
    assert response.generate_calls == [
        {
            "user_message": "Напиши пост",
            "summary": "summary",
            "facts_json": {"brand_name": "Brand"},
            "last_messages": memory.recent_messages[-10:],
            "url_summaries": None,
        }
    ]
    assert image.calls == [
        {
            "text": "Напиши пост",
            "user_id": "user-1",
            "request_id": "request-1",
            "facts": {"brand_name": "Brand"},
        }
    ]
    assert memory.append_calls == [
        {"user_id": "user-1", "role": "user", "text": "Напиши пост"},
        {"user_id": "user-1", "role": "assistant", "text": "Готовый ответ"},
    ]


def test_handle_applies_image_result_and_persists_visible_reply(monkeypatch):
    async def fake_scope_guard(_text, use_llm_fallback):
        assert use_llm_fallback is True
        return True, None

    monkeypatch.setattr(chat_service_module, "scope_guard", fake_scope_guard)
    monkeypatch.setattr(chat_service_module, "detect_intent", lambda text: "creative")

    url_data = SimpleNamespace(url_summaries=[{"title": "Brand page"}])
    image_result = SimpleNamespace(
        image={"status": "done", "images": [{"url": "/images/img-1.png"}]},
        reply="Сгенерировал креатив ✅",
        follow_up_question="Сделать ещё вариант?",
        actions=[{"type": "suggestion", "text": "Ещё вариант"}],
    )
    service, memory, response, image = build_service(
        url_context=SimpleNamespace(
            data=url_data,
            used_url=True,
            has_url_intent=True,
        ),
        image_result=image_result,
    )

    result = asyncio.run(
        service.handle(
            user_id="user-1",
            text="Сделай креатив по https://example.com",
        )
    )

    assert result == {
        "reply": "Сгенерировал креатив ✅",
        "follow_up_question": "Сделать ещё вариант?",
        "actions": [{"type": "suggestion", "text": "Ещё вариант"}],
        "debug": {"intent": "creative", "used_url": True},
        "image": {"status": "done", "images": [{"url": "/images/img-1.png"}]},
    }
    assert response.generate_calls[0]["url_summaries"] == [{"title": "Brand page"}]
    assert image.calls[0]["request_id"] == "request-1"
    assert memory.append_calls == [
        {
            "user_id": "user-1",
            "role": "user",
            "text": "Сделай креатив по https://example.com",
        },
        {"user_id": "user-1", "role": "assistant", "text": "Готовый ответ"},
        {
            "user_id": "user-1",
            "role": "assistant",
            "text": "Сгенерировал креатив ✅",
        },
    ]
