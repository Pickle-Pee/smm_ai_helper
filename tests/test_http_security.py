import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.config import settings
from app.db import get_session
from app.routers import tasks_router, brand_profile_router, chat_router, images_router, agents_router
from app.services.task_history_service import TaskHistoryService
from bot.backend import actor_headers


@pytest.fixture
def secured_app(monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "test-service-secret")
    app = FastAPI()
    for router in (tasks_router, brand_profile_router, chat_router, images_router, agents_router):
        app.include_router(router)
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))

    async def session():
        yield db

    app.dependency_overrides[get_session] = session
    return app, db


def request(app, method, path, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(run())


@pytest.mark.parametrize("method,path,payload", [
    ("GET", "/tasks/1", None), ("GET", "/tasks/by_user/100", None),
    ("GET", "/brand-profile/100", None), ("PATCH", "/brand-profile/100", {"tone": "private"}),
    ("POST", "/chat/message", {"user_id": "tg:100", "text": "hello"}),
    ("POST", "/tasks/start", {"agent_type": "strategy", "task_description": "test"}),
    ("POST", "/images/generate", {"message": "banner"}),
    ("GET", "/images/" + "a" * 32 + ".png", None),
])
def test_credentials_required_before_resource_access(secured_app, method, path, payload):
    app, db = secured_app
    assert request(app, method, path, json=payload).status_code == 401
    db.scalar.assert_not_called()


@pytest.mark.parametrize("path,payload", [
    ("/chat/message", {"user_id": "tg:200", "text": "private"}),
    ("/tasks/start", {"user": {"telegram_id": 200}, "agent_type": "strategy", "task_description": "x"}),
    ("/agents/strategy/run", {"user": {"telegram_id": 200}, "agent_type": "strategy", "task_description": "x", "answers": {}}),
])
def test_authenticated_bot_cannot_substitute_payload_owner(secured_app, path, payload):
    app, _ = secured_app
    assert request(app, "POST", path, json=payload, headers=actor_headers(100)).status_code == 403


def test_foreign_profile_task_and_session_are_denied(secured_app):
    app, db = secured_app
    headers = actor_headers(100)
    assert request(app, "GET", "/brand-profile/200", headers=headers).status_code == 403
    assert request(app, "GET", "/tasks/by_user/200", headers=headers).status_code == 403
    assert request(app, "GET", "/tasks/9", headers=headers).status_code == 404
    db.scalar.return_value = "200"
    assert request(app, "POST", "/tasks/answer", headers=headers,
                   json={"session_id": "foreign", "key": "x", "value": "y"}).status_code == 404


def test_nonempty_task_history_serializes_datetime_through_http(secured_app, monkeypatch):
    app, _ = secured_app
    task = SimpleNamespace(id=1, agent_type="strategy", task_description="saved", created_at=datetime(2026, 9, 8, 12, 0))
    monkeypatch.setattr(TaskHistoryService, "get_recent_tasks_by_telegram_id", AsyncMock(return_value=[task]))
    response = request(app, "GET", "/tasks/by_user/100", headers=actor_headers(100))
    assert response.status_code == 200
    assert response.json()[0]["created_at"] == "2026-09-08T12:00:00"


def test_missing_server_secret_fails_closed(secured_app, monkeypatch):
    app, _ = secured_app
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "")
    assert request(app, "GET", "/tasks/1", headers=actor_headers(100)).status_code == 503


def test_image_owner_is_checked_after_restart(secured_app, monkeypatch, tmp_path):
    from app.services.image_orchestrator import ImageOrchestrator
    app, _ = secured_app
    monkeypatch.setattr(settings, "IMAGE_STORAGE_PATH", str(tmp_path))
    image_id = ImageOrchestrator()._save_image(b"saved image", "tg:100")
    assert request(app, "GET", f"/images/{image_id}.png", headers=actor_headers(200)).status_code == 404
    result = request(app, "GET", f"/images/{image_id}.png", headers=actor_headers(100))
    assert result.status_code == 200 and result.content == b"saved image"


def test_callback_uses_clicking_actor_for_payload_and_new_actions(monkeypatch):
    import bot.handlers.chat as chat
    captures = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            captures.append(kwargs)
            return SimpleNamespace(status_code=200, json=lambda: {"reply": "done", "actions": [{"text": "continue"}]})
    status = SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())
    message = SimpleNamespace(from_user=SimpleNamespace(id=999), answer=AsyncMock(return_value=status))
    callback = SimpleNamespace(data="action:key", from_user=SimpleNamespace(id=100), message=message, answer=AsyncMock())
    monkeypatch.setattr(chat.httpx, "AsyncClient", Client)
    monkeypatch.setattr(chat, "_chat_action_indicator", AsyncMock())
    monkeypatch.setattr(chat, "_long_request_indicator", AsyncMock())
    monkeypatch.setattr(chat, "ACTION_STORE", {"100": {"key": "Continue"}})
    asyncio.run(chat.on_action(callback))
    assert captures[0]["json"]["user_id"] == "tg:100"
    assert captures[0]["headers"]["X-Telegram-User-ID"] == "100"
    assert "999" not in chat.ACTION_STORE
    assert "continue" in chat.ACTION_STORE["100"].values()


def test_long_telegram_text_is_complete_and_emoji_safe():
    from bot.rendering import split_text
    text = 'Маркетинг 🙂\n' * 2000
    chunks = split_text(text)
    assert ''.join(chunks) == text
    assert all(len(chunk.encode('utf-16-le')) // 2 <= 3500 for chunk in chunks)
